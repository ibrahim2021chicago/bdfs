#!/usr/libexec/platform-python
import logging
import sys
import socket
from subprocess import PIPE, run, TimeoutExpired
import re
import os
import shlex
from pathlib import Path

sys.path.append('/banktools/itm6/BofAScripts/pylib/usr/local/lib/python3.6/site-packages/')
from bofautils.basicpyt import *
from bofautils.authentication import *

class Tacmd:
    def __init__(self, component='HUB', hostname=None, logref='basic_logger'):
        """
        component: 'HUB' or 'TEPS' (default is HUB)
        hostname: target host for login (defaults to local hostname)
        """
        self.component = component.upper()
        self.hostname = hostname or socket.gethostname()
        self.session_home = f"/banktools/itm6/tmp/{self.hostname}/.ptacmd"
        Path(self.session_home).mkdir(parents=True, exist_ok=True)
        self.log = logging.getLogger(logref)
        self.cacheFile = "/dev/shm/tepadmin.n.cache"
        self.string_check = "<ISTATE>True"
        self.string_check2 = "<ASTATE>True"
        if self.component == 'TEPS':
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
            self.log.critical(f"tacmd command not found on server for {self.component}")

    def login(self):
        user, pd = "", ""
        try:
            with open(self.cacheFile, 'r') as fp:
                for line in fp:
                    if self.string_check in line or self.string_check2 in line:
                        ID = re.findall(r'<ID>(.*)</ID>', line)
                        PWD = re.findall(r'<PD>(.*)</PD>', line)
                        if ID and PWD:
                            user = str(ID[0])
                            pd = str(PWD[0])
        except Exception as e:
            self.log.error(f"Unable to process the Auth cachefile - Error : {e}")
            return None, None

        if len(user) > 3:
            try:
                key = encrypt_decrypt()
                new_user = encrypt_decrypt(key, user)
                password = encrypt_decrypt(key, pd)
            except Exception as e:
                self.log.error(f"Unable to use encrypt_decrypt module - Error : {e}")
                return None, None

            login_input = f"{self.hostname} -u {new_user} -p {password}\n"
            try:
                p = run([self.TACMD_DIR, self.login_cmd, "-stdin"],
                        env=dict(os.environ, HOME=self.session_home),
                        stdout=PIPE, stderr=PIPE,
                        input=login_input, encoding='ascii', timeout=600)
                self.log.info(p.stdout)
                if self.component == 'HUB':
                    hub_matches = ["secondary hub", "connect to a hub monitoring", "unexpected system error"]
                    if any(match in (p.stdout.lower() + p.stderr.lower()) for match in hub_matches):
                        self.log.warning("HUB retry logic activated, attempting re-login...")
                        return self.login()
                return p.stdout, p.stderr
            except TimeoutExpired:
                self.log.error("tacmd command timeout occurred")
                return None, "tacmd command timeout occurred"
            except Exception as e:
                self.log.error(f"Unable to run the tacmd command - Error : {e}")
                return None, f"Unable to run the tacmd command - Error : {e}"
        else:
            self.log.error("Unable to process the cachefile, or credentials invalid")
            return None, "Unable to process the cachefile"

    def command(self, cmdargs="", retry=0):
        args = shlex.split(cmdargs)
        args.insert(0, self.TACMD_DIR)
        env = dict(os.environ, HOME=self.session_home)
        try:
            p = run(args, env=env,
                    stdout=PIPE, stderr=PIPE,
                    input='y\n', encoding='ascii', timeout=600)
            output = p.stdout + p.stderr
            if p.returncode == 0:
                self.log.info(output)
                return 0, re.sub(r'\n', '', re.sub('Are you sure you want to..or no. \n', '', output))
            else:
                if self.component == 'HUB' and retry < 1:
                    if "are not logged in" in output.lower():
                        self.login()
                        return self.command(cmdargs, 1)
                    if "unexpected system error" in output.lower():
                        self.login()
                        return self.command(cmdargs, 1)
                self.log.error(f"ReturnCode [{p.returncode}] {output}")
                return p.returncode, "[" + str(p.returncode) + "] " + output
        except TimeoutExpired:
            self.log.error("tacmd command timeout occurred")
            return 9, "tacmd command timeout occurred"
        except Exception as e:
            self.log.error(f"Unable to run the tacmd command - Error : {e}")
            return 8, f"Unable to run the tacmd command - Error : {e}"

    def set_hostname(self, hostname):
        """
        Set or change the hostname and reset session directory accordingly.
        """
        self.hostname = hostname
        self.session_home = f"/banktools/itm6/tmp/{self.hostname}/.ptacmd"
        Path(self.session_home).mkdir(parents=True, exist_ok=True)
        self.log.info(f"Hostname updated to {hostname}, session directory set.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
