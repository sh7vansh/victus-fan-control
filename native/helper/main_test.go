package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
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
		case "daemon":
			if len(args) != 3 {
				os.Exit(2)
			}
			ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
			defer stop()
			err = runDaemon(ctx, args[2], fixtureControls{c}, uint32(os.Getuid()))
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
	for _, args := range [][]string{{"--session"}, {"--session", c.root}, {"--daemon"}, {"--root", c.root}, {"--fixture-session", c.root}, {"--verify-profile", "/etc/passwd"}} {
		if err := run(args, strings.NewReader(""), io.Discard, c, 1000); err == nil {
			t.Fatalf("Accepted unsupported CLI: %v", args)
		}
	}
}

func TestDaemonChecksKernelPeerIdentity(t *testing.T) {
	path := filepath.Join(t.TempDir(), "peer.sock")
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	client, err := net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	peer, err := listener.AcceptUnix()
	if err != nil {
		t.Fatal(err)
	}
	defer peer.Close()
	if err := authorizePeer(peer, uint32(os.Getuid())); err != nil {
		t.Fatalf("Own UID denied: %v", err)
	}
	if os.Getuid() != 0 && authorizePeer(peer, uint32(os.Getuid()+1)) == nil {
		t.Fatal("Another user's peer accepted")
	}
}

func TestDaemonRefusesNonSocketPathAndInvalidUID(t *testing.T) {
	c := fixture(t)
	path := filepath.Join(t.TempDir(), "unrelated-file")
	os.WriteFile(path, []byte("keep"), 0600)
	if runDaemon(context.Background(), path, c, uint32(os.Getuid())) == nil {
		t.Fatal("Replaced unrelated file with socket")
	}
	if value := text(path); value == nil || *value != "keep" {
		t.Fatal("Unrelated file changed")
	}
	for _, uid := range []string{"-1", "4294967296", "invalid"} {
		if run([]string{"--daemon", "--allow-uid", uid}, strings.NewReader(""), io.Discard, c, 0) == nil {
			t.Fatalf("Accepted invalid UID: %s", uid)
		}
	}
}

func TestDaemonServerAndRejectsUnprivileged(t *testing.T) {
	c := fixture(t)
	if err := run([]string{"--daemon"}, strings.NewReader(""), io.Discard, c, 1000); err == nil {
		t.Fatal("Accepted unprivileged daemon run")
	}

	sockPath := filepath.Join(t.TempDir(), "test.sock")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	completed := make(chan error, 1)
	go func() { completed <- runDaemon(ctx, sockPath, c, uint32(os.Getuid())) }()

	var conn net.Conn
	var err error
	for i := 0; i < 20; i++ {
		time.Sleep(10 * time.Millisecond)
		conn, err = net.Dial("unix", sockPath)
		if err == nil {
			break
		}
	}
	if err != nil {
		t.Fatalf("Could not connect to daemon socket: %v", err)
	}
	defer conn.Close()
	info, err := os.Stat(sockPath)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("Socket must be private: %v, %v", info, err)
	}

	reader := bufio.NewReader(conn)
	greeting, err := reader.ReadBytes('\n')
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(greeting), `"ready":true`) {
		t.Fatalf("Unexpected greeting: %s", greeting)
	}

	fmt.Fprintf(conn, "{\"id\":1,\"operation\":\"profile\",\"value\":\"quiet\"}\n")
	line, err := reader.ReadBytes('\n')
	if err != nil {
		t.Fatal(err)
	}
	var resp reply
	if err := json.Unmarshal(line, &resp); err != nil {
		t.Fatal(err)
	}
	if !resp.OK || resp.ID == nil || *resp.ID != 1 {
		t.Fatalf("Unexpected daemon reply: %+v", resp)
	}
	if err := c.verify("profile", "quiet"); err != nil {
		t.Fatal(err)
	}
	cancel()
	if err := <-completed; err != nil {
		t.Fatal(err)
	}
}
