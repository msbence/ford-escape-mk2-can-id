import os
import sys
import time
import curses
import select
import argparse

HIGHLIGHT_DURATION = 0.75

# USAGE: python3 sniffer.py /dev/ttyACM0

class FrameData:
    def __init__(self, bus, can_id_str, dlc, data_bytes, now):
        self.bus = bus
        self.can_id_str = can_id_str
        try:
            self.sort_key = (bus, int(can_id_str, 16))
        except ValueError:
            self.sort_key = (bus, 0)
        self.dlc = dlc
        self.data = data_bytes
        self.change_times = [0.0] * len(data_bytes)

    def update(self, dlc, new_bytes, now):
        self.dlc = dlc
        if len(new_bytes) > len(self.change_times):
            self.change_times.extend([now] * (len(new_bytes) - len(self.change_times)))
        
        for i in range(len(new_bytes)):
            if i >= len(self.data) or new_bytes[i] != self.data[i]:
                self.change_times[i] = now
        self.data = new_bytes

def parse_line(line):
    line = line.strip()
    if not line or '[' not in line or ']' not in line:
        return None
    try:
        left, right = line.split('[', 1)
        dlc_str, data_str = right.split(']', 1)
        
        if '|' in data_str:
            data_str = data_str.split('|', 1)[0]

        left_parts = left.strip().split()
        if len(left_parts) >= 3 and left_parts[0] in ("RX", "TX"):
            bus = left_parts[1].upper()
            can_id_str = left_parts[2]
        elif len(left_parts) >= 2:
            bus = left_parts[0].upper()
            can_id_str = left_parts[1]
        else:
            bus = "??"
            can_id_str = left_parts[0]

        dlc = int(dlc_str.strip())
        data_bytes = data_str.strip().split()
        return bus, can_id_str, dlc, data_bytes
    except Exception:
        return None

def main(stdscr, data_fd, initial_bus):
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_RED, -1)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, curses.COLOR_GREEN, -1)
    
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    # Set the data file descriptor to strictly non-blocking mode
    os.set_blocking(data_fd, False)
    poller = select.poll()
    poller.register(data_fd, select.POLLIN)

    frames = {}
    last_draw = 0
    draw_interval = 0.04
    bus_filter = initial_bus
    dec_mode = False
    rx_buffer = ""

    while True:
        # 1. Process all queued keyboard presses immediately
        while True:
            key = stdscr.getch()
            if key == -1:
                break
            if key in (ord('q'), ord('Q')):
                return
            elif key in (ord('c'), ord('C')):
                frames.clear()
                stdscr.erase()
            elif key in (ord('d'), ord('D')):
                dec_mode = not dec_mode
                stdscr.erase()
            elif key == ord('1'):
                bus_filter = "HS"
                stdscr.erase()
            elif key == ord('2'):
                bus_filter = "MS"
                stdscr.erase()
            elif key == ord('0'):
                bus_filter = None
                stdscr.erase()

        # 2. Read raw chunks from serial/pipe without ever blocking
        if poller.poll(5):
            try:
                chunk = os.read(data_fd, 4096)
                if chunk:
                    rx_buffer += chunk.decode('ascii', errors='ignore')
                    if '\n' in rx_buffer:
                        lines = rx_buffer.split('\n')
                        rx_buffer = lines[-1] # Keep incomplete trailing line for next read
                        now = time.monotonic()
                        for line in lines[:-1]:
                            parsed = parse_line(line)
                            if parsed:
                                bus, can_id_str, dlc, data_bytes = parsed
                                key_id = f"{bus}_{can_id_str}"
                                if key_id in frames:
                                    frames[key_id].update(dlc, data_bytes, now)
                                else:
                                    frames[key_id] = FrameData(bus, can_id_str, dlc, data_bytes, now)
            except BlockingIOError:
                pass
            except OSError:
                pass

        # 3. Redraw UI at 25 FPS
        now = time.monotonic()
        if now - last_draw >= draw_interval:
            last_draw = now
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()

            visible_keys = [
                k for k in frames.keys() 
                if bus_filter is None or frames[k].bus == bus_filter
            ]
            sorted_keys = sorted(visible_keys, key=lambda k: frames[k].sort_key)

            filter_label = bus_filter if bus_filter else "ALL"
            mode_label = "DEC" if dec_mode else "HEX"
            col_width = 50 if dec_mode else 42
            
            header_text = (
                f" CAN Sniffer [{filter_label} | {mode_label}] | IDs: {len(sorted_keys)}/{len(frames)} "
                f"| Keys: [0] All [1] HS [2] MS [d] Hex/Dec [c] Clear [q] Quit "
            )
            try:
                stdscr.addstr(0, 0, header_text[:max_x-1], curses.color_pair(4) | curses.A_BOLD | curses.A_REVERSE)
            except curses.error:
                pass

            avail_rows = max_y - 2
            if avail_rows <= 0:
                stdscr.refresh()
                continue

            for idx, k in enumerate(sorted_keys):
                col = idx // avail_rows
                row = (idx % avail_rows) + 1
                x_pos = col * col_width

                if x_pos + col_width > max_x:
                    break

                f = frames[k]
                prefix = f"{f.bus:<2} {f.can_id_str:<5} [{f.dlc}] "
                
                try:
                    stdscr.addstr(row, x_pos, prefix, curses.color_pair(3))
                    cur_x = x_pos + len(prefix)

                    for b_idx, byte_str in enumerate(f.data):
                        is_changed = (now - f.change_times[b_idx]) <= HIGHLIGHT_DURATION
                        attr = (curses.color_pair(2) | curses.A_BOLD) if is_changed else curses.color_pair(1)
                        
                        if dec_mode:
                            try:
                                val_str = f"{int(byte_str, 16):>3} "
                            except ValueError:
                                val_str = f"{byte_str:>3} "
                            step = 4
                        else:
                            val_str = f"{byte_str} "
                            step = 3

                        stdscr.addstr(row, cur_x, val_str, attr)
                        cur_x += step
                except curses.error:
                    pass

            stdscr.refresh()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Terminal CAN Bus Sniffer")
    parser.add_argument("device", nargs="?", default=None, help="Serial device path (e.g., /dev/ttyACM0)")
    parser.add_argument("-b", "--bus", choices=["HS", "MS", "hs", "ms"], help="Initial bus filter (HS or MS)")
    args = parser.parse_args()
    
    initial_bus = args.bus.upper() if args.bus else None

    if args.device:
        # Open serial port directly without blocking
        data_fd = os.open(args.device, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    else:
        # Duplicate piped stdin to a new FD, then attach real terminal keyboard to FD 0 for curses
        data_fd = os.dup(0)
        tty_fd = os.open('/dev/tty', os.O_RDONLY)
        os.dup2(tty_fd, 0)
        os.close(tty_fd)

    try:
        curses.wrapper(main, data_fd, initial_bus)
    finally:
        os.close(data_fd)
