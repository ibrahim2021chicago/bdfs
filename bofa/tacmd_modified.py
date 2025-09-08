import logging
import sys
import socket
from subprocess import PIPE, run, TimeoutExpired
import re
import os
import shlex
from pathlib import Path

class Tacmd:
    def __init__(self, mode="hub", host=None, logref='basic_logger'):
        """
        mode: 'hub' or 'teps'
        host: explicit host (default is local hostname)
        """
        self.mode = mode.lower()
        self.host = host if host else socket.gethostname()
        Path(f'/banktools/itm6/tmp/{self.host}/.ptacmd').mkdir(parents=True, exist_ok=True)
        self.log = logging.getLogger(logref)
        self.cacheFile = f"/dev/shm/{self.host}.n.cache"
        self.string_check = "<ISTATE>True"
        self.string_check2 = "<ASTATE>True"

        # Determine tacmd binary and login command by mode
        if self.mode == "teps":
            tacmd_candidates = ["/banktools/itm6/TEP_HOME/bin/tacmd", "/banktools/itm6/bin/tacmd"]
            self.login_cmd = "tepslogin"
        else:
            tacmd_candidates = ["/banktools/itm6/HUB_HOME/bin/tacmd", "/banktools/itm6/bin/tacmd"]
            self.login_cmd = "login"
        self.TACMD_DIR = None
        for candidate in tacmd_candidates:
            if os.path.isfile(candidate):
                self.TACMD_DIR = candidate
                break
        if not self.TACMD_DIR:
            self.log.critical("tacmd command not found on server.")
            raise FileNotFoundError("tacmd binary not found.")

        # Set HOME path to be per-host for session safety
        self.session_home = f"/banktools/itm6/tmp/{self.host}/.ptacmd"

    def login(self, user, password, timeout=600):
        args = [
            self.TACMD_DIR,
            self.login_cmd,
            "-s", self.host,
            "-u", user,
            "-p", password,
            "-t", str(timeout)
        ]
        try:
            self.log.info(f"Running: {' '.join(args)}")
            # Set session HOME to prevent cache collisions
            env = dict(os.environ, HOME=self.session_home)
            p = run(args, env=env, stdout=PIPE, stderr=PIPE, encoding='ascii', timeout=timeout)
            if p.returncode == 0:
                self.log.info("Login successful.")
                return 0, p.stdout.strip()
            else:
                self.log.error(f"Login failed: [{p.returncode}] {p.stdout} {p.stderr}")
                return p.returncode, p.stdout + p.stderr
        except TimeoutExpired:
            self.log.error("tacmd login command timeout occurred")
            return 9, "tacmd login command timeout occurred"
        except Exception as e:
            self.log.error(f"Unable to run the tacmd command - Error : {e}")
            return 8, f"Unable to run the tacmd command - Error : {e}"

    def command(self, cmdargs, timeout=600, retry=0):
        """
        Runs an arbitrary tacmd CLI command (post-login).
        Adds smart retry logic only for HUB mode.
        """
        args = shlex.split(cmdargs)
        args.insert(0, self.TACMD_DIR)
        env = dict(os.environ, HOME=self.session_home)
        try:
            p = run(args, env=env, stdout=PIPE, stderr=PIPE, input='y\n', encoding='ascii', timeout=timeout)
            output = p.stdout + p.stderr
            if p.returncode == 0:
                self.log.info(f"Command succeeded: {output}")
                return 0, re.sub(r'\n', '', re.sub('Are you sure you want to..or no. \n', '', output))
            else:
                # Only apply smart retry logic for HUB (not TEPS)
                if self.mode == "hub" and retry < 1:
                    # Advanced HUB fallback matching:
                    hub_fail_patterns = ["secondary hub", "connect to a hub monitoring", "unexpected system error"]
                    if any(pattern in output.lower() for pattern in hub_fail_patterns):
                        self.log.warning(f"Retrying HUB login and retrying command after error: {output}")
                        # You could implement fallback host logic here if needed
                        self.login(user="hubuser", password="hubpass")  # Supply correct credentials
                        return self.command(cmdargs, timeout, retry=retry+1)
                self.log.error(f"Command failed: [{p.returncode}] {output}")
                return p.returncode, output
        except TimeoutExpired:
            self.log.error("tacmd command timeout occurred")
            return 9, "tacmd command timeout occurred"
        except Exception as e:
            self.log.error(f"Unable to run the tacmd command - Error : {e}")
            return 8, f"Unable to run the tacmd command - Error : {e}"

    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

# CLI interface for manual/test use
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import argparse
    parser = argparse.ArgumentParser(description="Tacmd HUB/TEPS control module")
    parser.add_argument('--mode', choices=['hub', 'teps'], default='hub')
    parser.add_argument('--host', default=None)
    parser.add_argument('--user', required=True)
    parser.add_argument('--password', required=True)
    parser.add_argument('--command', default=None, help='extra tacmd CLI command to run (post-login)')

    args = parser.parse_args()
    tacmd = Tacmd(mode=args.mode, host=args.host)
    r, o = tacmd.login(user=args.user, password=args.password)
    print(f"Login result: [{r}] {o}")
    if args.command:
        r2, o2 = tacmd.command(args.command)
        print(f"Command result: [{r2}] {o2}")
