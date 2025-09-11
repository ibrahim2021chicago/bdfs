#!/usr/libexec/platform-python
import logging
import sys
import socket
from subprocess import PIPE, run, TimeoutExpired
import re
import os
import time
import shlex
from pathlib import Path
sys.path.append('/banktools/itm6/BofAScripts/pylib/usr/local/lib/python3.6/site-packages/')
from bofautils.basicpyt import *
from bofautils.authentication import *

class Tacmd:
    def __init__(self, logref='basic_logger', hostname=None):
        # Create logger
        self.log = logging.getLogger(logref)
        self.hostname = hostname or socket.gethostname()
        self.session_home = f"/banktools/itm6/tmp/{self.hostname}/.ptacmd"
        Path(self.session_home).mkdir(parents=True, exist_ok=True)
        self.cacheFile = "/dev/shm/tepadmin.acache"
        self.string_check = "<ISTATE>True"
        self.string_check2 = "<ASTATE>True"
        self.setHub()
    
    def setHostname(self, hostname):
        self.hostname = hostname
        self.session_home = f"/banktools/itm6/tmp/{self.hostname}/.ptacmd"
        Path(self.session_home).mkdir(parents=True, exist_ok=True)

    def setHub(self):
        if os.path.isfile("/banktools/itm6/HUB_HOME/bin/tacmd"):
            self.TACMD_DIR = "/banktools/itm6/HUB_HOME/bin/tacmd"
        elif os.path.isfile("/banktools/itm6/bin/tacmd"):
            self.TACMD_DIR = "/banktools/itm6/bin/tacmd"
        else:
            self.log.critical("tacmd command not found on server.")
        self.login_cmd = "login"
    
    def setTeps(self):
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
                        ID = re.findall(r'<ID>(.*)</ID>',line)
                        PWD = re.findall(r'<PD>(.*)</PD>',line)
                        user = str(ID[2:-2])
                        pd = str(PWD[2:-2])
                    elif self.string_check2 in line:
                        ID = re.findall(r'<ID>(.*)</ID>',line)
                        PWD = re.findall(r'<PD>(.*)</PD>',line)
                        user = str(ID[2:-2])
                        pd = str(PWD[2:-2])
            
            if len(user) > 3:
                try:
                    key = encrypt_decrypt()
                    new_user = encrypt_decrypt(key, user)
                    password = encrypt_decrypt(key, pd)
                except Exception as e:
                    self.log.error(f"Unable to use encrypt_decrypt module - Error : {e}")
                    return None, None
                try:
                    p = run([self.TACMD_DIR, self.login_cmd, '-stdin'], env=dict(os.environ, HOME=self.session_home), stdout=PIPE, stderr=PIPE,
                        input=f'-s {self.hostname} -u {new_user} -p {password}\n', encoding='ascii', timeout=600)
                    if p.returncode == 0:
                        self.log.info(p.stdout)
                    else:
                        if self.login_cmd == "login":
                            matches = ["secondary hub", "connect to a hub monitoring", "unexpected system error"]

                            if any(x in p.stdout.lower() + p.stderr.lower() for x in matches):
                                if os.path.exists("/banktools/itm6/HUB_HOME/config/.ConfigData/kmsenv"):
                                    pattern = re.compile("^hub_.*?\|MIRROR\|(?P<BHTEM>.*?)\|")
                                    for line in open("/banktools/itm6/HUB_HOME/config/.ConfigData/kmsenv", "r").readlines():
                                        match = pattern.match(line)
                                        if match:
                                            lBHTEM = match.group("BHTEM")
                                            p = run([self.TACMD_DIR, self.login_cmd, '-stdin'], env=dict(os.environ, HOME=self.session_home), stdout=PIPE,stderr=PIPE,
                                                input=f"-s {lBHTEM} -u {new_user} -p {password}\n", encoding='ascii', timeout=600)
                                            if p.returncode == 0:
                                                self.log.info(p.stdout)
                                            else:
                                                self.log.info(p.stdout + p.stderr)
                                                return p.stdout + p.stderr
                        self.log.info(p.stdout + p.stderr)
                        return p.stdout + p.stderr
                except subprocess.TimeoutExpired:
                    p.terminate()
                    self.log.error("tacmd command timeout occurred")
                
                except Exception as e:
                    self.log.error(f"Unable to run the tacmd command - Error : {e}")
            
            else:
                self.log.error(f"Unable to process the Auth cachefile - Error : {e}")
        except Exception as e:
            self.log.error(f"Unable to process the cachefile -  Error : {e}")
            

    def command(self, cmdargs = "", retry=0):
        try:
            args = shlex.split(cmdargs)
            args.insert(0,self.TACMD_DIR)
            p = run(args, env=dict(os.environ, HOME=self.session_home), stdout=PIPE, stderr=PIPE,
                    input=f'y\n', encoding='ascii',timeout=600)
            if p.returncode == 0:
                self.log.info(p.stdout)
                return 0, re.sub(r'^\n', '', re.sub(r'Are you sure you want to.*or no. :\n?', '', p.stdout))
            else:
                if retry < 1:
                    if not "are not logged in" in p.stdout.lower() + p.stderr.lower():
                        if p.stdout == "" and p.stderr == "":
                            self.login()
                            return self.command( cmdargs, 1)
                        else:
                            if "unexpected system error" in p.stdout.lower() + p.stderr.lower():
                                self.login()
                                return self.command( cmdargs, 1)
                        #    self.log.error("ReturnColde [" + str(p.returncode) + "]" +p.stdout + p.stderr)
                    
                    else:
                        self.login()
                        return self.command(cmdargs, 1)
                self.log.error("ReturnCode [" + str(p.returncode) + "]" +p.stdout + p.stderr)
                return p.returncode, "[" + str(p.returncode) + "] " +p.stdout + p.stderr
        except subprocess.TimeoutExpired:
            p.terminate()
            self.log.error(f"tacmd command timeout occurred")
            return 9, "tacmd command timeout occurred"
        
        except Exception as e:
            self.log.error(f"Unable to run the tacmd command  -  Error : {e}")
            return 8, f"Unable to run the tacmd command  -  Error : {e}"
                                                                     

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass