// Host helper for fan monitoring and sysfs writes.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

var version = "development"

const maxLine = 1024
const idleTimeout = 20 * time.Second
const defaultSocketPath = "/run/victus-fan-control.sock"

var profiles = map[string]bool{"quiet": true, "cool": true, "balanced": true, "performance": true}

type controls struct{ root string }
type snapshot struct {
	Profile    *string   `json:"profile"`
	Choices    []string  `json:"choices"`
	Controller *string   `json:"controller"`
	Mode       *int      `json:"mode"`
	RPM        [2]*int   `json:"rpm"`
	Labels     [2]string `json:"labels"`
}

func text(path string) *string {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	value := strings.TrimSpace(string(data))
	return &value
}
func number(path string) *int {
	value := text(path)
	if value == nil {
		return nil
	}
	result, err := strconv.Atoi(*value)
	if err != nil || result < 0 {
		return nil
	}
	return &result
}
func (c controls) profilePath() string {
	return filepath.Join(c.root, "firmware/acpi/platform_profile")
}
func (c controls) controller() string {
	parent := filepath.Join(c.root, "devices/platform/hp-wmi/hwmon")
	candidates, _ := filepath.Glob(filepath.Join(parent, "hwmon*"))
	for _, candidate := range candidates {
		target, err := filepath.EvalSymlinks(candidate)
		if err != nil || filepath.Dir(target) != parent {
			continue
		}
		name := filepath.Base(target)
		suffix := strings.TrimPrefix(name, "hwmon")
		if suffix == name || suffix == "" || strings.Trim(suffix, "0123456789") != "" {
			continue
		}
		driver := text(filepath.Join(target, "name"))
		if driver != nil && *driver == "hp" {
			return target
		}
	}
	return ""
}
func (c controls) snapshot() snapshot {
	state := snapshot{Profile: text(c.profilePath()), Choices: []string{}, Labels: [2]string{"CPU fan", "GPU fan"}}
	if choices := text(c.profilePath() + "_choices"); choices != nil {
		state.Choices = append(state.Choices, strings.Fields(*choices)...)
	}
	controller := c.controller()
	if controller != "" {
		state.Controller = &controller
		state.Mode = number(filepath.Join(controller, "pwm1_enable"))
		for index := 0; index < 2; index++ {
			state.RPM[index] = number(filepath.Join(controller, fmt.Sprintf("fan%d_input", index+1)))
			if label := text(filepath.Join(controller, fmt.Sprintf("fan%d_label", index+1))); label != nil && *label != "" {
				state.Labels[index] = *label
			}
		}
	}
	return state
}
func validSetting(operation, value string) bool {
	return operation == "profile" && profiles[value] || operation == "fan" && (value == "0" || value == "2")
}
func (c controls) target(operation, value string) (string, error) {
	if !validSetting(operation, value) {
		return "", errors.New("Unsupported fan-control setting.")
	}
	if operation == "profile" {
		choices := text(c.profilePath() + "_choices")
		if choices != nil {
			for _, choice := range strings.Fields(*choices) {
				if value == choice {
					return c.profilePath(), nil
				}
			}
		}
		return "", errors.New("This profile is not supported by your firmware.")
	}
	controller := c.controller()
	if controller == "" {
		return "", errors.New("The HP fan controller is unavailable.")
	}
	return filepath.Join(controller, "pwm1_enable"), nil
}
func (c controls) change(operation, value string) error {
	path, err := c.target(operation, value)
	if err != nil {
		return err
	}
	// O_CREAT is deliberately absent; refuse missing or substituted attributes.
	fd, err := syscall.Open(path, syscall.O_WRONLY|syscall.O_TRUNC|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return err
	}
	file := os.NewFile(uintptr(fd), path)
	defer file.Close()
	payload := []byte(value + "\n")
	written, err := file.Write(payload)
	if err == nil && written != len(payload) {
		err = io.ErrShortWrite
	}
	return err
}
func (c controls) verify(operation, value string) error {
	path, err := c.target(operation, value)
	if err != nil {
		return err
	}
	actual := text(path)
	if actual == nil || *actual != value {
		return errors.New("The setting did not stay applied. The firmware or another power management app may have changed it.")
	}
	return nil
}

type changer interface{ change(string, string) error }
type reply struct {
	ID    *int64 `json:"id"`
	OK    bool   `json:"ok"`
	Error string `json:"error,omitempty"`
}
type request struct {
	id               int64
	operation, value string
}

func parse(line []byte) (request, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(line, &fields); err != nil {
		return request{}, err
	}
	if len(fields) != 3 {
		return request{}, errors.New("Unexpected request fields.")
	}
	for _, name := range []string{"id", "operation", "value"} {
		if _, ok := fields[name]; !ok {
			return request{}, errors.New("Unexpected request fields.")
		}
	}
	var item request
	if err := json.Unmarshal(fields["id"], &item.id); err != nil || item.id <= 0 || item.id > 1<<53 {
		return request{}, errors.New("Invalid request identifier.")
	}
	if err := json.Unmarshal(fields["operation"], &item.operation); err != nil {
		return request{}, errors.New("Invalid operation.")
	}
	if err := json.Unmarshal(fields["value"], &item.value); err != nil {
		return request{}, errors.New("Invalid setting.")
	}
	if !validSetting(item.operation, item.value) {
		return request{}, errors.New("Unsupported fan-control setting.")
	}
	return item, nil
}
func special(line []byte, operation string) bool {
	var fields map[string]json.RawMessage
	if json.Unmarshal(line, &fields) != nil || len(fields) != 1 {
		return false
	}
	var value string
	return json.Unmarshal(fields["operation"], &value) == nil && value == operation
}
func serve(input io.Reader, output io.Writer, c changer, timeout time.Duration) error {
	encoder := json.NewEncoder(output)
	if err := encoder.Encode(map[string]bool{"ready": true}); err != nil {
		return err
	}
	lines := make(chan []byte)
	done := make(chan struct{})
	defer close(done)
	go func() {
		defer close(lines)
		scanner := bufio.NewScanner(input)
		scanner.Buffer(make([]byte, maxLine+2), maxLine+2)
		for scanner.Scan() {
			line := bytes.Clone(scanner.Bytes())
			if len(line) > maxLine {
				return
			}
			select {
			case lines <- line:
			case <-done:
				return
			}
		}
	}()
	var timer *time.Timer
	if timeout > 0 {
		timer = time.NewTimer(timeout)
		defer timer.Stop()
	}
	reset := func() {
		if timer != nil {
			if !timer.Stop() {
				select {
				case <-timer.C:
				default:
				}
			}
			timer.Reset(timeout)
		}
	}
	for {
		var timeoutChan <-chan time.Time
		if timer != nil {
			timeoutChan = timer.C
		}
		select {
		case <-timeoutChan:
			return nil
		case line, ok := <-lines:
			if !ok || special(line, "close") {
				return nil
			}
			if special(line, "ping") {
				reset()
				continue
			}
			item, err := parse(line)
			response := reply{}
			if err == nil {
				response.ID = &item.id
				err = c.change(item.operation, item.value)
			}
			response.OK = err == nil
			if err != nil {
				response.Error = err.Error()
			} else {
				reset()
			}
			if err := encoder.Encode(response); err != nil {
				return err
			}
		}
	}
}

// Peer credentials come from the kernel, never from a client protocol field.
func authorizePeer(conn *net.UnixConn, allowedUID uint32) error {
	raw, err := conn.SyscallConn()
	if err != nil {
		return err
	}
	var cred *syscall.Ucred
	var socketErr error
	if err := raw.Control(func(fd uintptr) {
		cred, socketErr = syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
	}); err != nil {
		return err
	}
	if socketErr != nil {
		return socketErr
	}
	if cred == nil || (cred.Uid != allowedUID && cred.Uid != 0) {
		return errors.New("This user is not authorized to control cooling.")
	}
	return nil
}

func runDaemon(ctx context.Context, socketPath string, c changer, allowedUID uint32) error {
	// The production socket is in root-owned /run. Refuse to remove other files.
	if info, err := os.Lstat(socketPath); err == nil {
		if info.Mode()&os.ModeSocket == 0 {
			return errors.New("Socket path is not a socket.")
		}
		if err := os.Remove(socketPath); err != nil {
			return err
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: socketPath, Net: "unix"})
	if err != nil {
		return err
	}
	defer listener.Close()
	// Restrict the socket before assigning ownership to the selected user.
	if err := os.Chmod(socketPath, 0600); err != nil {
		return err
	}
	if os.Geteuid() == 0 {
		if err := os.Chown(socketPath, int(allowedUID), -1); err != nil {
			return err
		}
	} else if allowedUID != uint32(os.Geteuid()) {
		return errors.New("Cannot assign socket to another user without root.")
	}
	done := make(chan struct{})
	defer close(done)
	go func() {
		select {
		case <-ctx.Done():
			listener.Close()
		case <-done:
		}
	}()
	for {
		conn, err := listener.AcceptUnix()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return nil
			}
			return err
		}
		if err := authorizePeer(conn, allowedUID); err != nil {
			conn.Close()
			continue
		}
		go func(nc *net.UnixConn) {
			defer nc.Close()
			_ = serve(nc, nc, c, 0)
		}(conn)
	}
}

func daemon(socketPath string, c controls, allowedUID uint32) error {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	return runDaemon(ctx, socketPath, c, allowedUID)
}

func run(args []string, input io.Reader, output io.Writer, c controls, uid int) error {
	if len(args) == 1 {
		switch args[0] {
		case "--snapshot":
			return json.NewEncoder(output).Encode(c.snapshot())
		case "--version":
			_, err := fmt.Fprintln(output, version)
			return err
		case "--session":
			if uid != 0 {
				return errors.New("Administrator authentication is required for fan changes.")
			}
			return serve(input, output, c, idleTimeout)
		case "--daemon":
			if uid != 0 {
				return errors.New("Administrator authentication is required to run the daemon.")
			}
			return daemon(defaultSocketPath, c, 0)
		}
	}
	if len(args) == 2 {
		switch args[0] {
		case "--verify-profile":
			return c.verify("profile", args[1])
		case "--verify-fan":
			return c.verify("fan", args[1])
		}
	}
	if len(args) == 3 && args[0] == "--daemon" && args[1] == "--allow-uid" {
		if uid != 0 {
			return errors.New("Administrator authentication is required to run the daemon.")
		}
		allowedUID, err := strconv.ParseUint(args[2], 10, 32)
		if err != nil {
			return errors.New("Invalid authorized user ID.")
		}
		return daemon(defaultSocketPath, c, uint32(allowedUID))
	}
	return errors.New("Expected --snapshot, --session, --daemon [--allow-uid UID], --version, --verify-profile VALUE, or --verify-fan VALUE.")
}
func main() {
	if err := run(os.Args[1:], os.Stdin, os.Stdout, controls{root: "/sys"}, os.Geteuid()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
