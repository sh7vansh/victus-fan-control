package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// This entry exists only in the separate Go test executable, never in the app.
func TestMain(m *testing.M) {
	flag.Parse()
	args := flag.Args()
	if len(args) > 0 {
		if len(args) < 2 {
			os.Exit(2)
		}
		mode, root := args[0], args[1]
		c := controls{root: root}
		var err error
		switch mode {
		case "session":
			if len(args) != 3 {
				os.Exit(2)
			}
			ms, failure := strconv.Atoi(args[2])
			if failure != nil {
				os.Exit(2)
			}
			err = serve(os.Stdin, os.Stdout, fixtureControls{c}, time.Duration(ms)*time.Millisecond)
		case "snapshot":
			state := c.snapshot()
			if state.Controller != nil {
				path := "/sys" + strings.TrimPrefix(*state.Controller, root)
				state.Controller = &path
			}
			err = json.NewEncoder(os.Stdout).Encode(state)
		case "verify-profile", "verify-fan":
			if len(args) != 3 {
				os.Exit(2)
			}
			err = c.verify(strings.TrimPrefix(mode, "verify-"), args[2])
		default:
			os.Exit(2)
		}
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		os.Exit(0)
	}
	os.Exit(m.Run())
}

type fixtureControls struct{ controls }

func (c fixtureControls) change(operation, value string) error {
	mode, _ := os.ReadFile(filepath.Join(c.root, "test-command"))
	if string(mode) == "reject" {
		return errors.New("Fixture rejected the write")
	}
	if string(mode) == "ignore" {
		return nil
	}
	return c.controls.change(operation, value)
}
func fixture(t *testing.T) controls {
	t.Helper()
	root := t.TempDir()
	values := map[string]string{
		"firmware/acpi/platform_profile":                    "balanced\n",
		"firmware/acpi/platform_profile_choices":            "quiet cool balanced performance\n",
		"devices/platform/hp-wmi/hwmon/hwmon42/name":        "hp\n",
		"devices/platform/hp-wmi/hwmon/hwmon42/pwm1_enable": "2\n",
		"devices/platform/hp-wmi/hwmon/hwmon42/fan1_input":  "0\n",
		"devices/platform/hp-wmi/hwmon/hwmon42/fan2_input":  "2576\n",
	}
	for name, value := range values {
		path := filepath.Join(root, name)
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(value), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return controls{root: root}
}
func TestSnapshotAndSafeWrites(t *testing.T) {
	c := fixture(t)
	state := c.snapshot()
	if state.Profile == nil || *state.Profile != "balanced" || state.RPM[0] == nil || *state.RPM[0] != 0 || *state.RPM[1] != 2576 {
		t.Fatalf("Wrong snapshot: %+v", state)
	}
	for _, item := range [][2]string{{"profile", "quiet"}, {"fan", "0"}, {"fan", "2"}} {
		if err := c.change(item[0], item[1]); err != nil {
			t.Fatal(err)
		}
		if err := c.verify(item[0], item[1]); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.verify("profile", "balanced"); err == nil {
		t.Fatal("Rejected readback went undetected")
	}
}
func TestRequestsCannotChoosePathsOrPrograms(t *testing.T) {
	cases := []string{`[]`, `null`, `{"id":1,"operation":"shell","value":"id"}`,
		`{"id":1,"operation":"profile","value":"quiet\nperformance"}`,
		`{"id":1,"operation":"fan","value":"1"}`, `{"id":true,"operation":"fan","value":"0"}`,
		`{"id":1,"operation":"fan","value":0}`, `{"id":0,"operation":"profile","value":"quiet"}`,
		`{"id":1,"operation":"profile","value":"quiet","path":"/etc/passwd"}`,
		`{"id":1,"operation":"profile","value":"quiet","command":"sh"}`,
		`{"id":1.2,"operation":"profile","value":"quiet"}`}
	for _, line := range cases {
		if _, err := parse([]byte(line)); err == nil {
			t.Errorf("Accepted unsafe request: %s", line)
		}
	}
}
func TestMissingAndSymlinkAttributesAreNotCreatedOrFollowed(t *testing.T) {
	c := fixture(t)
	if err := os.Remove(c.profilePath()); err != nil {
		t.Fatal(err)
	}
	if err := c.change("profile", "quiet"); err == nil {
		t.Fatal("Created missing attribute")
	}
	other := filepath.Join(c.root, "unrelated")
	os.WriteFile(other, []byte("unchanged"), 0600)
	os.Symlink(other, c.profilePath())
	if err := c.change("profile", "quiet"); err == nil {
		t.Fatal("Followed attribute symlink")
	}
	if value := text(other); value == nil || *value != "unchanged" {
		t.Fatal("Unrelated file modified")
	}
}
func TestUnsupportedControllerAndProfilesAreRejected(t *testing.T) {
	c := fixture(t)
	os.WriteFile(c.profilePath()+"_choices", []byte("balanced"), 0600)
	if c.change("profile", "quiet") == nil {
		t.Fatal("Unsupported profile accepted")
	}
	os.WriteFile(filepath.Join(c.controller(), "name"), []byte("other"), 0600)
	if c.change("fan", "0") == nil || c.snapshot().Controller != nil {
		t.Fatal("Other controller accepted")
	}
}
func TestUnavailableAndInvalidReadingsAreNotZero(t *testing.T) {
	c := fixture(t)
	os.WriteFile(filepath.Join(c.controller(), "fan1_input"), []byte("bad"), 0600)
	os.Remove(filepath.Join(c.controller(), "fan2_input"))
	state := c.snapshot()
	if state.RPM[0] != nil || state.RPM[1] != nil {
		t.Fatal("Invalid readings presented as zero")
	}
	os.RemoveAll(c.root)
	payload, err := json.Marshal(c.snapshot())
	if err != nil || !bytes.Contains(payload, []byte(`"choices":[]`)) {
		t.Fatalf("Unavailable snapshot has invalid shape: %s", payload)
	}
}
func TestSessionHandlesMultipleCommandsAndRejectsOversizedInput(t *testing.T) {
	c := fixture(t)
	input := "not-json\n" + `{"id":1,"operation":"profile","value":"quiet"}` + "\n" + `{"id":2,"operation":"fan","value":"0"}` + "\n"
	var output bytes.Buffer
	if err := serve(strings.NewReader(input), &output, c, time.Second); err != nil {
		t.Fatal(err)
	}
	decoder := json.NewDecoder(&output)
	var ready map[string]bool
	decoder.Decode(&ready)
	if !ready["ready"] {
		t.Fatal("No session handshake")
	}
	for index := 0; index < 3; index++ {
		var response reply
		if err := decoder.Decode(&response); err != nil {
			t.Fatal(err)
		}
		if response.OK != (index > 0) {
			t.Fatalf("Unexpected reply: %+v", response)
		}
	}
	if err := c.verify("profile", "quiet"); err != nil {
		t.Fatal(err)
	}
	output.Reset()
	if err := serve(strings.NewReader(strings.Repeat("x", 2048)+"\n"), &output, c, time.Second); err != nil {
		t.Fatal(err)
	}
	if err := c.verify("profile", "quiet"); err != nil {
		t.Fatal(err)
	}
}
func TestIdleAndEOFCloseWithoutWriting(t *testing.T) {
	c := fixture(t)
	reader, writer := io.Pipe()
	defer reader.Close()
	defer writer.Close()
	start := time.Now()
	if err := serve(reader, io.Discard, c, 30*time.Millisecond); err != nil {
		t.Fatal(err)
	}
	if time.Since(start) > time.Second {
		t.Fatal("Idle timeout did not expire")
	}
	if err := c.verify("profile", "balanced"); err != nil {
		t.Fatal(err)
	}
	if err := serve(strings.NewReader(""), io.Discard, c, time.Second); err != nil {
		t.Fatal(err)
	}
}
func TestProductionCLIRejectsAlternativeRootsAndUnprivilegedSessions(t *testing.T) {
	c := fixture(t)
	for _, args := range [][]string{{"--session"}, {"--session", c.root}, {"--root", c.root}, {"--fixture-session", c.root}, {"--verify-profile", "/etc/passwd"}} {
		if err := run(args, strings.NewReader(""), io.Discard, c, 1000); err == nil {
			t.Fatalf("Accepted unsupported CLI: %v", args)
		}
	}
}
