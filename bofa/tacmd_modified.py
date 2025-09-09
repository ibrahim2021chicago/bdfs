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
    def __init__(self, logref='basic_logger'):
        # Create logger
        self.log = logging.getLogger(logref)
        
        self.session_home = "/banktools/itm6/tmp/hub/.ptacmd"
        Path(self.session_home).mkdir(parents=True, exist_ok=True)
        self.cacheFile = "/dev/shm/tepadmin.n.cache"
        self.string_check = "<ISTATE>True"
        self.string_check2 = "<ASTATE>True"

        if os.path.isfile("/banktools/itm6/HUB_HOME/bin/tacmd"):
            self.TACMD_DIR = "/banktools/itm6/HUB_HOME/bin/tacmd"
        elif os.path.isfile("/banktools/itm6/bin/tacmd"):
            self.TACMD_DIR = "/banktools/itm6/bin/tacmd"
        else:
            self.log.critical("tacmd command not found on server.")
        self.login_cmd = "login"

    def teps(self):
        self.session_home = "/banktools/itm6/tmp/teps/.ptacmd"
        Path(self.session_home).mkdir(parents=True, exist_ok=True)
        
        if os.path.isfile("/banktools/itm6/TEP_HOME/bin/tacmd"):
            self.TACMD_DIR = "/banktools/itm6/TEP_HOME/bin/tacmd"
        elif os.path.isfile("/banktools/itm6/bin/tacmd"):
            self.TACMD_DIR = "/banktools/itm6/bin/tacmd"
        else:
            self.log.critical("TEPS tacmd command not found on server.")
            raise FileNotFoundError("TEPS tacmd command not found.")
        self.login_cmd = "tepslogin"

    def login(self):
        try:
            user = ""
            pd = ""
            with open(self.cacheFile, 'r') as fp:
                for line in fp:
                    if self.string_check in line:
                        ID = re.findall(r'<ID>(.*)</ID>', line)
                        PWD = re.findall(r'<PD>(.*)</PD>', line)
                        user = str(ID[0])
                        pd = str(PWD[0])
                    elif self.string_check2 in line:
                        ID = re.findall(r'<ID>(.*)</ID>', line)
                        PWD = re.findall(r'<PD>(.*)</PD>', line)
                        user = str(ID[0])
                        pd = str(PWD[0])
            if len(user) > 3:
                try:
                    key = encrypt_decrypt()
                    new_user = encrypt_decrypt(key, user)
                    password = encrypt_decrypt(key, pd)
                except Exception as e:
                    self.log.error(f"Unable to use encrypt_decrypt module - Error : {e}")
                    return None, None

                hostname = socket.gethostname()
                login_input = f"{hostname} -u {new_user} -p {password}\n"

                p = run([self.TACMD_DIR, self.login_cmd, "-stdin"],
                        env=dict(os.environ, HOME=self.session_home),
                        stdout=PIPE, stderr=PIPE,
                        input=login_input, encoding='ascii', timeout=600)
                if p.returncode == 0:
                    self.log.info(p.stdout)
                    # HUB retry logic matches
                    matches = ["secondary hub", "connect to a hub monitoring", "unexpected system error"]
                    if any(match in p.stdout.lower() + p.stderr.lower() for match in matches):
                        if os.path.exists("/banktools/itm6/HUB_HOME/config/.ConfigData/kmsenv"):
                            pattern = re.compile(r"hub-.*?MIRROR (?P<BHTEM>[\w\d\-]+)")
                            for line in open("/banktools/itm6/HUB_HOME/config/.ConfigData/kmsenv", "r").readlines():
                                match = pattern.match(line)
                                if match:
                                    BHTEM = match.group("BHTEM")
                                    p = run([self.TACMD_DIR, 'login', '-stdin'], 
                                            env=dict(os.environ, HOME=self.session_home), 
                                            stdout=PIPE, stderr=PIPE,
                                            input=f"{BHTEM} -u {new_user} -p {password}\n", 
                                            encoding='ascii', timeout=600)
                                    if p.returncode == 0:
                                        self.log.info(p.stdout)
                                        return p.stdout, None
                        else:
                            self.log.error("Config file does not exist for fallback host.")
                    return p.stdout, None
                else:
                    self.log.error(f"Login failed: {p.stdout} {p.stderr}")
                    return p.stdout + p.stderr
            else:
                self.log.error("Cache file user invalid or too short.")
                return None, None
        except TimeoutExpired:
            self.log.error("tacmd command timeout occurred")
            return None, "tacmd command timeout occurred"
        except Exception as e:
            self.log.error(f"Unable to run the tacmd command - Error : {e}")
            return None, f"Unable to run the tacmd command - Error : {e}"

    def command(self, cmdargs="", retry=0):
        args = shlex.split(cmdargs)
        args.insert(0, self.TACMD_DIR)
        env = dict(os.environ, HOME=self.session_home)
        try:
            p = run(args, env=env,
                    stdout=PIPE, stderr=PIPE,
                    input='y\n', encoding='ascii', timeout=600)
            if p.returncode == 0:
                self.log.info(p.stdout)
                return 0, re.sub(r'\n', '', re.sub('Are you sure you want to..or no. \n', '', p.stdout))
            else:
                if retry < 1:
                    if "are not logged in" in p.stdout.lower() + p.stderr.lower():
                        self.login()
                        return self.command(cmdargs, 1)
                    if "unexpected system error" in p.stdout.lower() + p.stderr.lower():
                        self.login()
                        return self.command(cmdargs, 1)
                self.log.error(f"ReturnCode [{p.returncode}] {p.stdout} {p.stderr}")
                return p.returncode, "[" + str(p.returncode) + "] " + p.stdout + p.stderr
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
