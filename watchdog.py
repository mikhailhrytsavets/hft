import subprocess
import time
import sys
import os
from datetime import datetime
import signal

def log_message(message, log_file="watchdog.log"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(log_entry + "\n")

def is_process_running(process):
    return process.poll() is None

def run_main():
    restart_count = 0
    while True:
        log_message("Starting main.py...")
        try:
            # Run main.py and monitor it
            process = subprocess.Popen([sys.executable, "main.py"])
            
            # Monitor the process
            while is_process_running(process):
                time.sleep(1)
            
            # Get the exit code
            exit_code = process.returncode
            restart_count += 1
            
            if exit_code == 0:
                log_message("main.py exited normally with code 0")
            else:
                log_message(f"main.py crashed with exit code {exit_code}")
            
            log_message(f"Restart attempt #{restart_count}. Restarting in 5 seconds...")
            time.sleep(5)
            
        except KeyboardInterrupt:
            log_message("Watchdog stopped by user")
            if process and is_process_running(process):
                process.terminate()
                process.wait()
            break
        except Exception as e:
            log_message(f"Error occurred: {str(e)}")
            time.sleep(5)

if __name__ == "__main__":
    log_message("Watchdog started")
    try:
        run_main()
    except KeyboardInterrupt:
        log_message("Watchdog stopped by user")
    except Exception as e:
        log_message(f"Fatal error: {str(e)}") 
