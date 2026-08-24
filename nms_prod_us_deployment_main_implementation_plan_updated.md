Objective:

Deploy a highly available Zabbix 7.0 monitoring platform with:

- PostgreSQL HA (Primary/Secondary with replication + VIP)
- Zabbix Server HA (Active/Standby)
- NGINX Web Frontend
- Regional Zabbix Proxies
- End-to-end monitoring with failover capabilities


Steps:

1. Pre-Implementation Activities

1.1 Validate Infrastructure:

- Confirm all servers running Rocky Linux 9
- Validate CPU, RAM, storage allocations per design
- Confirm IP assignments for:
    DB VIP
    Zabbix VIP
    Node IPs
- Network Interface - 10.90.5.0/24 (VLAN 5)


1.2 Updates & Setup (All Nodes):

- sudo dnf update -y
- Run ansible r9-common role to install all Belcan-specific configs


2. PostgreSQL HA Deployment

Implementation Note: PostgreSQL HA, Patroni, etcd and PostgreSQL VIP automatic failover are implemented under the separate PostgreSQL Automatic Failover change request(CHG0108668). The PostgreSQL HA steps below are retained for implementation/reference context. Current PostgreSQL service management is performed by Patroni.

2.1 Install PostgreSQL (Both Nodes):

- sudo dnf install -y postgresql-server postgresql


2.2 Initialize and Start:

- sudo postgresql-setup --initdb --unit postgresql
- sudo systemctl enable --now postgresql


2.3 Configure password encryption:

- sudo -u postgres psql
- ALTER SYSTEM SET password_encryption = 'scram-sha-256';
- SELECT pg_reload_conf();

Verify:
- SHOW password_encryption;

Expected output:
scram-sha-256

2.4 Create Database:

- sudo -u postgres psql
- CREATE DATABASE zabbix;
- CREATE USER zabbix;
- \password zabbix
- GRANT ALL PRIVILEGES ON DATABASE zabbix TO zabbix;
- \q


2.5 Configure Remote Access:

Edit  /var/lib/pgsql/data/postgresql.conf

- listen_addresses = '*'

Edit /var/lib/pgsql/data/pg_hba.conf

- host zabbix zabbix <zabbix_primary_ip>/32 scram-sha-256
- host zabbix zabbix <zabbix_secondary_ip>/32 scram-sha-256
- host zabbix zabbix <nginx_ip>/32 scram-sha-256

Restart
- sudo systemctl restart postgresql.service


3. PostgreSQL Replication Setup

Implementation Note: The PostgreSQL replication and automatic failover configuration is managed by Patroni under the completed PostgreSQL Automatic Failover change request(CHG0108668). Refer to that change for the authoritative Patroni/etcd implementation.

3.1 Configure Primary:

Edit /var/lib/pgsql/data/postgresql.conf

- wal_level = replica
- max_wal_senders = 10
- wal_keep_size = 128MB
- archive_mode = on
- archive_command = 'cp %p /var/lib/pgsql/archive/%f'


- sudo mkdir -p /var/lib/pgsql/archive
- sudo chown postgres:postgres /var/lib/pgsql/archive


Edit /var/lib/pgsql/data/pg_hba.conf and add replication access:
- host replication zabbix_repl <secondary_ip>/32 scram-sha-256

Restart DB:
- sudo systemctl restart postgresql.service

Create replication role:
- sudo -u postgres psql
- CREATE ROLE zabbix_repl WITH REPLICATION LOGIN;
- \password zabbix_repl
- \q


3.2 Build Standby Server:

Make sure PostgreSQL is not running:
- sudo systemctl stop postgresql.service

Remove Initialized Database:
- sudo rm -rf /var/lib/pgsql/data/*

Build Standby:
sudo -u postgres pg_basebackup \
 -h <primary_ip> \
 -U zabbix_repl \
 -D /var/lib/pgsql/data \
 --wal-method=stream \
 --checkpoint=fast \
 -P \
 -R

Start PostgreSQL:
- systemctl start postgresql.service

Verify Standby:
- sudo -u postgres psql -c "SELECT pg_is_in_recovery();"

Expected output:
"t"

Verify Replication (Primary):
- sudo -u postgres psql
- SELECT application_name, client_addr, state, sync_state FROM pg_stat_replication;

CG server should be listed.



4. PostgreSQL VIP Configuration (Keepalived)

Implementation Note: The current PostgreSQL VIP implementation is Patroni-aware. Keepalived uses the Patroni `/primary` health check to ensure that the VIP is owned only by the current PostgreSQL Leader. The authoritative implementation is documented in the completed PostgreSQL Automatic Failover change request(CHG0108668).

4.1 Install Keepalived (Both Servers)
- sudo dnf install -y keepalived
- sudo systemctl enable keepalived

4.2 Create PostgreSQL Health Check Script (Both Servers)

- sudo vim /usr/local/bin/check_postgres.sh


#!/bin/bash

systemctl is-active --quiet postgresql || exit 1

ROLE=$(sudo -u postgres psql -Atqc "SELECT pg_is_in_recovery();")

if [ "$ROLE" = "f" ]; then
    exit 0
else
    exit 1
fi


- sudo chmod +x /usr/local/bin/check_postgres.sh


4.3 Configure Keepalived on Primary:

- sudo vim /etc/keepalived/keepalived.conf


global_defs {
    router_id MU_PGSQL
}

vrrp_script chk_postgres {
    script "/usr/local/bin/check_postgres.sh"
    interval 2
    weight -20
}

vrrp_instance VI_PG {
    state MASTER
    interface ens33
    virtual_router_id 51
    priority 200
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass BelcanVIP
    }

    virtual_ipaddress {
        <db_vip>/24
    }

    track_script {
        chk_postgres
    }
}



4.4 Configure Keepalived on Secondary:

- sudo vim /etc/keepalived/keepalived.conf


global_defs {
    router_id CG_PGSQL
}

vrrp_script chk_postgres {
    script "/usr/local/bin/check_postgres.sh"
    interval 2
    weight -20
}

vrrp_instance VI_PG {
    state BACKUP
    interface ens33
    virtual_router_id 51
    priority 100
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass BelcanVIP
    }

    virtual_ipaddress {
        <db_vip>/24
    }

    track_script {
        chk_postgres
    }
}





5. Zabbix Server HA Deployment

5.1 Install (Both Nodes):

- sudo dnf install -y epel-release

Exclude zabbix packages in epel repo to avoid conflict. Add this line in /etc/yum.repos.d/epel.repo under [epel] section:

- excludepkgs=zabbix*

- wget https://repo.zabbix.com/zabbix/7.0/rhel/9/x86_64/zabbix-release-latest-7.0.el9.noarch.rpm
- sudo rpm -Uvh zabbix-release-latest-7.0.el9.noarch.rpm
- sudo dnf clean all && dnf makecache
- sudo dnf install -y zabbix-server-pgsql zabbix-agent2 zabbix-sql-scripts postgresql


5.2 Import DB Schema (Primary Only):

-zcat /usr/share/zabbix-sql-scripts/postgresql/server.sql.gz | \
  psql -h <db_vip> -U zabbix -d zabbix


5.3 Configure HA:

Edit /etc/zabbix/zabbix_server.conf

Primary

- DBHost=<db_vip>
- DBName=zabbix
- DBUser=zabbix
- DBPassword=<password>

- HANodeName=munms01
- NodeAddress=<primary_ip>:10051

Secondary

- DBHost=<db_vip>
- DBName=zabbix
- DBUser=zabbix
- DBPassword=<password>

- HANodeName=cgnms01
- NodeAddress=<secondary_ip>:10051


5.4 Start Services:
- systemctl enable --now zabbix-server zabbix-agent2


5.5 Verify HA Status

Run this from either server:
- sudo zabbix_server -V

Open the Zabbix UI:

Administration --> HA Nodes

Both nodes would be listed something like:

munms01              Active
cgnms01                Standby


5.6 Install Keepalived (Both Zabbix Servers)
- sudo dnf install -y keepalived


5.7 Create Health Check Script (Both Zabbix Servers)

- sudo vim /usr/local/bin/check_zabbix.sh


#!/bin/bash

systemctl is-active --quiet zabbix-server

exit $?


- sudo chmod +x /usr/local/bin/check_zabbix.sh



5.8 Configure Keepalived on Primary (MU):

- sudo vim /etc/keepalived.conf


global_defs {
    router_id ZBX_MU
}

vrrp_script chk_zabbix {
    script "/usr/local/bin/check_zabbix.sh"
    interval 2
    weight 20
}

vrrp_instance VI_ZBX {
    state MASTER
    interface ens33
    virtual_router_id 52
    priority 150
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass BelcanZBX
    }

    virtual_ipaddress {
        10.90.5.11/24
    }

    track_script {
        chk_zabbix
    }
}



5.8 Configure Keepalived on Secondary (CG):

- sudo vim /etc/keepalived.conf


global_defs {
    router_id ZBX_CG
}

vrrp_script chk_zabbix {
    script "/usr/local/bin/check_zabbix.sh"
    interval 2
    weight 20
}

vrrp_instance VI_ZBX {
    state BACKUP
    interface ens33
    virtual_router_id 52
    priority 100
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass BelcanZBX
    }

    virtual_ipaddress {
        10.90.5.11/24
    }

    track_script {
        chk_zabbix
    }
}


5.9 Start Keepalived

- sudo systemctl enable keepalived

- ip addr

Should show the VIP on MU and no VIP should present on CG





6. NGINX Web Frontend

6.1 Install:

Exclude zabbix packages in epel repo to avoid conflict. Add this line in /etc/yum.repos.d/epel.repo under [epel] section:
- excludepkgs=zabbix*

- wget https://repo.zabbix.com/zabbix/7.0/rhel/9/x86_64/zabbix-release-latest-7.0.el9.noarch.rpm
- sudo rpm -Uvh zabbix-release-latest-7.0.el9.noarch.rpm
- sudo dnf clean all && dnf makecache
- sudo dnf install -y nginx php-fpm php-pgsql zabbix-web zabbix-web-pgsql zabbix-nginx-conf zabbix-agent2


6.2 Configure:

Edit /etc/php.in

- date.timezone = UTC


6.3 Start the services

-sudo systemctl enable --now php-fpm.service nginx.service zabbix-agent2.service


6.4 Open the Zabbix frontend and complete the Zabbix Web Installer:

- https://nms-us.belcan.com/

Configure DB connection:

- Database type - PostgreSQL
- Database host - PostgreSQL VIP
- Database name - zabbix
- User - zabbix
- Password - Zabbix DB Password

Uncheck "Database TLS encryption" and leave all other fields as default.

Provide a Zabbix Server Name and finish the installation.

Login with default credentials:
Admin/zabbix





7. Proxy Deployment (Per Region)

7.1 Install:

Exclude zabbix packages in epel repo to avoid conflict. Add this line in /etc/yum.repos.d/epel.repo under [epel] section:
- excludepkgs=zabbix*

- wget https://repo.zabbix.com/zabbix/7.0/rhel/9/x86_64/zabbix-release-latest-7.0.el9.noarch.rpm
- sudo rpm -Uvh zabbix-release-latest-7.0.el9.noarch.rpm
- sudo dnf clean all && dnf makecache
- sudo dnf install -y zabbix-proxy-pgsql zabbix-sql-scripts postgresql-server zabbix-agent2


7.2 Configure PostgreSQL:

- sudo postgresql-setup --initdb --unit postgresql
- sudo systemctl enable --now postgresql

Create database:
- sudo -u postgres psql
- CREATE ROLE zabbix_proxy_<region> LOGIN;
- \password zabbix_proxy_<region>
- CREATE DATABASE zabbix_proxy_<region> OWNER zabbix_proxy_<region>;
- \q


7.3 Import schema
- sudo -u postgres psql -d zabbix_proxy_<region> -f /usr/share/zabbix-sql-scripts/postgresql/proxy.sql


7.4 Configure Proxy:

Edit /etc/zabbix/zabbix_proxy.conf
- ProxyMode=0
- Server=<zabbix_vip>
- Hostname=<proxy_server_name>
- DBHost=127.0.0.1
- DBName=zabbix_proxy_<region>
- DBUser=zabbix_proxy_<region>
- DBPassword=<password>


7.5 Start services:
- systemctl enable --now zabbix-proxy zabbix-agent2


7.6 Validate:
- psql -h 127.0.0.1 -U zabbix_proxy_<region> -d zabbix_proxy_<region>





8. Validation Plan

8.1 PostgreSQL / Patroni / etcd Connectivity:

Validate connectivity between all three nodes, run from each node:
- munmssql01
- cgnmssql01
- munmsetcd01

- nc -zv 10.90.5.3 2379
- nc -zv 10.90.5.4 2379
- nc -zv 10.90.5.27 2379

Validate etcd cluster health:
- sudo etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health
- sudo etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 member list

Expected:
- Three etcd members.
- All members healthy.
- Quorum established.

8.2 etcd Peer Connectivity:

Validate TCP 2380 between all three etcd members:
- nc -zv 10.90.5.3 2380
- nc -zv 10.90.5.4 2380
- nc -zv 10.90.5.27 2380

8.3 Patroni Cluster Validation:

Run from either PostgreSQL node:
- sudo patronictl -c /etc/patroni/patroni.yml list

Validate Patroni REST API:
- curl http://10.90.5.3:8008/patroni
- curl http://10.90.5.4:8008/patroni

Expected:
- One Leader.
- One Replica.
- Cluster healthy.

8.4 PostgreSQL Connectivity:

Validate PostgreSQL through the PostgreSQL VIP:
- nc -zv 10.90.5.12 5432
- psql -h 10.90.5.12 -U zabbix -d zabbix

Verify the database role through the VIP:
- SELECT pg_is_in_recovery();

Expected when connected through the PostgreSQL VIP:
- f

8.5 Zabbix Server Connectivity:

Validate Zabbix Server port using Zabbix Server VIP:
- nc -zv 10.90.5.11 10051

8.6 Proxy Connectivity:

For each Zabbix Proxy:
- nc -zv 10.90.5.11 10051

Verify the proxy database and schema exists:
- psql -h 127.0.0.1 -U <zabbix_proxy_user> -d <zabbix_proxy_db>
- \dt

8.7 Agent Connectivity:

Verify Agent 2 status:
- sudo systemctl status zabbix-agent2
- ss -lntp | grep 10050

8.8 Functional Validation:

Log in to the Zabbix UI and verify:
- Zabbix UI accessible through NGINX HTTPS.
- Production hostname is https://nms-us.belcan.com.
- Zabbix Server nodes configured correctly.
- Zabbix Server HA status shows 1 Active / 1 Standby.
- PostgreSQL cluster shows 1 Leader / 1 Replica.
- PostgreSQL VIP is assigned to the current Primary.
- Proxies show Online.
- Hosts show Available/Green.
- Latest data is being received.
- No unexpected database or proxy errors.

9. Failover Testing

Dependency: PostgreSQL automatic failover using Patroni, etcd and Keepalived was implemented and validated under the separate PostgreSQL Automatic Failover change request(CHG0108668), which is already completed and closed. This change focuses on validating Zabbix application continuity and HA behavior against that infrastructure and does not repeat the full PostgreSQL HA implementation.

9.1 PostgreSQL / Zabbix Integration Failover Validation

The detailed PostgreSQL automatic failover procedure is covered by the completed PostgreSQL Automatic Failover change request.

For this Zabbix deployment change, validate application continuity during/after a previously approved PostgreSQL failover test.

Verify:
- Patroni reports one Leader and one Replica.
- PostgreSQL VIP 10.90.5.12 is assigned to the current Leader.
- Zabbix Server can connect to PostgreSQL through 10.90.5.12.
- Zabbix frontend remains accessible.
- Zabbix Server remains operational.
- Latest monitoring data continues to be received.
- No unexpected database connection errors are observed.

From the Zabbix Server:
- nc -zv 10.90.5.12 5432
- psql -h 10.90.5.12 -U zabbix -d zabbix

9.2 Zabbix Server HA Failover Test

Verify the initial Zabbix HA state:
- 1 Active
- 1 Standby

Identify the current Active Zabbix Server node.

On the Active node:
- sudo systemctl stop zabbix-server

Verify in the Zabbix UI that the Standby node automatically becomes Active.

Confirm:
- Zabbix UI remains accessible.
- New Active Zabbix Server is operational.
- Hosts continue reporting data.
- Proxies remain Online.
- PostgreSQL connectivity remains available through the PostgreSQL VIP.
- No critical errors are generated.

9.3 Zabbix Server Recovery

On the stopped Zabbix Server:
- sudo systemctl start zabbix-server

Verify:
- sudo systemctl status zabbix-server

Confirm in the Zabbix UI that the recovered server rejoins the HA cluster as Standby.

Expected:
- 1 Active
- 1 Standby

9.4 PostgreSQL VIP Continuity Validation

Following PostgreSQL failover or controlled switchover, verify that the PostgreSQL VIP remains reachable and follows the current Primary.

- sudo patronictl -c /etc/patroni/patroni.yml list
- ip addr
- nc -zv 10.90.5.12 5432

From the Zabbix Server:
- psql -h 10.90.5.12 -U zabbix -d zabbix

Verify:
- Zabbix database remains accessible.
- No application-level database connection errors are observed.
- Latest monitoring data continues to update.

9.5 End-to-End HA Validation

Verify the complete production workflow:

PostgreSQL Primary / Leader
        ⇩
Patroni manages PostgreSQL role
        ⇩
PostgreSQL VIP 10.90.5.12 follows current Primary
        ⇩
Zabbix Server connects through PostgreSQL VIP
        ⇩
Zabbix Server HA maintains Active/Standby
        ⇩
Zabbix Proxies remain Online
        ⇩
Hosts continue reporting data

Record, where applicable:
- Failover/switchover initiation time.
- PostgreSQL recovery/promotion time from the completed HA test.
- VIP movement time.
- Zabbix application recovery time.
- Any monitoring/data gap.
- Errors observed in application/system logs.

9.6 Failover Test Success Criteria

The Zabbix deployment validation will be considered successful when:
- PostgreSQL HA reports 1 Leader + 1 Replica.
- PostgreSQL VIP 10.90.5.12 is assigned to the current Primary.
- Zabbix Server can connect to PostgreSQL through the VIP.
- Zabbix Server HA successfully maintains 1 Active + 1 Standby.
- Zabbix Server failover successfully changes the Active/Standby role.
- Recovered Zabbix Server rejoins as Standby.
- Zabbix Proxies remain Online.
- Monitoring data continues to be collected.
- Zabbix frontend remains accessible through HTTPS.
- No split-brain condition is observed.
- No unresolved critical errors remain in Zabbix Server, Zabbix Proxy, NGINX or PostgreSQL integration logs.

10. Backup and Configuration Protection

10.1 PostgreSQL Zabbix Database Backup

Run the backup from the designated backup server, or from an approved PostgreSQL/utility server that has network access to the PostgreSQL VIP.

The backup connects to the PostgreSQL VIP, which always points to the current Primary.

Verify VIP connectivity:
- nc -zv 10.90.5.12 5432

Perform the backup:
- pg_dump \
    -h 10.90.5.12 \
    -U zabbix \
    -d zabbix \
    -Fc \
    -f /backup/zabbix/zabbix_$(date +%Y%m%d_%H%M%S).dump

Verify:
- ls -lh /backup/zabbix/

Validate the dump:
- pg_restore --list /backup/zabbix/<backup-file>.dump



10.2 PostgreSQL Proxy Database Backup

Each Zabbix Proxy has its own PostgreSQL database.

Run on each proxy server:
- mkdir -p /backup/zabbix-proxy

Backup:
- pg_dump \
    -h 127.0.0.1 \
    -U <zabbix_proxy_user> \
    -d <zabbix_proxy_db> \
    -Fc \
    -f /backup/zabbix-proxy/zabbix_proxy_<region>_$(date +%Y%m%d_%H%M%S).dump

Validate:
- pg_restore --list /backup/zabbix-proxy/<backup-file>.dump


10.3 Zabbix Server Configuration Backup

Run on both Zabbix Server nodes:
- sudo tar -czf \
    /backup/zabbix_server_config_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
    /etc/zabbix/

Verify:
- ls -lh /backup/zabbix_server_config_*

Protect the backup:
- sudo chmod 600 /backup/zabbix_server_config_*.tar.gz

10.4 Zabbix Proxy Configuration Backup

Run on each Zabbix Proxy:
- sudo tar -czf \
    /backup/zabbix_proxy_config_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
    /etc/zabbix/

Protect the backup:
- sudo chmod 600 /backup/zabbix_proxy_config_*.tar.gz

10.5 NGINX Configuration and TLS Backup

Run on NGINX server:
- sudo tar -czf \
    /backup/nginx_config_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
    /etc/nginx/

Back up certificates/keys:
- sudo tar -czf \
    /backup/zabbix_certs_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
    /etc/zabbix/certs/

Protect private-key backups:
- sudo chmod 600 /backup/zabbix_certs_*.tar.gz

10.6 Patroni / etcd / Keepalived Configuration Reference

Patroni, etcd and PostgreSQL Keepalived configuration were implemented under the separate PostgreSQL Automatic Failover change request(CHG0108668).

The authoritative configuration and backup procedure for:
- /etc/patroni/
- /etc/etcd/
- etcd data snapshot
- /etc/keepalived/

is maintained under that completed change request.

If the organization's recovery procedure requires these files to be included in the Zabbix application recovery package, verify that the approved HA configuration backups exist and are available in the enterprise backup repository.

10.7 Backup Verification and Transfer

After completing the backups:
- df -h /backup
- find /backup -type f -ls

Verify that the required backups exist:
- Zabbix PostgreSQL database.
- Zabbix Proxy PostgreSQL databases.
- Zabbix Server configuration.
- Zabbix Proxy configuration.
- NGINX configuration.
- TLS certificates/keys where approved.
- HA configuration backups as required by the recovery procedure.

For the Zabbix PostgreSQL database and proxy databases, validate the dump using pg_restore --list.

Transfer all required backups from the local staging location to the organization's approved enterprise backup repository.

The local /backup directory should be considered temporary staging unless it is explicitly part of the organization's backup infrastructure.

11. Post-Implementation Validation and Change Closure

11.1 PostgreSQL Network Security

Verify PostgreSQL listeners:
- sudo ss -lntp | grep 5432

Review PostgreSQL access rules:
- sudo cat /var/lib/pgsql/data/pg_hba.conf

Ensure PostgreSQL access is restricted to the required:
- Zabbix Server nodes.
- PostgreSQL HA nodes.
- Approved application networks.
- Required administrative/monitoring sources.

Avoid broad rules such as:
0.0.0.0/0

unless explicitly required and approved.

11.2 PostgreSQL HA / Keepalived Validation

The PostgreSQL HA implementation is managed by Patroni and is covered by the completed PostgreSQL Automatic Failover change request(CHG0108668).

For final integration validation:
- sudo systemctl status patroni
- sudo systemctl status keepalived
- sudo patronictl -c /etc/patroni/patroni.yml list

Expected:
- 1 Leader.
- 1 Replica.

Check VIP ownership:
- ip addr

The PostgreSQL VIP 10.90.5.12 must be assigned to the current Primary.

Test:
- nc -zv 10.90.5.12 5432

11.3 Zabbix Server HA Validation

On both Zabbix Server nodes:
- sudo systemctl status zabbix-server

Verify in the Zabbix UI:
- 1 Active.
- 1 Standby.

Confirm the final HA state after failover and recovery testing.

11.4 Zabbix Proxy Validation

On each Proxy:
- sudo systemctl status zabbix-proxy
- sudo systemctl status zabbix-agent2

Verify connectivity to the Zabbix Server:
- nc -zv 10.90.5.11 10051

In the Zabbix UI:
Data collection -> Proxies

Confirm each required proxy shows:
- Online.

11.5 NGINX / HTTPS Validation

On the NGINX server:
- sudo nginx -t

Expected:
- syntax is ok.
- test is successful.

Verify:
- sudo systemctl status nginx
- sudo systemctl status php-fpm

Test HTTP:
- curl -I http://nms-us.belcan.com

Confirm HTTP redirects to HTTPS.

Test HTTPS:
- curl -vk https://nms-us.belcan.com

Verify the certificate:
- openssl s_client \
    -connect nms-us.belcan.com:443 \
    -servername nms-us.belcan.com </dev/null 2>/dev/null \
    | openssl x509 -noout -subject -issuer -dates

Confirm:
- Subject/SAN includes nms-us.belcan.com.
- Certificate is within its validity period.
- HTTPS connection is successful.
- No unexpected certificate warning is presented to the client.

11.6 Service Validation

PostgreSQL / Patroni nodes:
- sudo systemctl status patroni
- sudo systemctl status keepalived
- sudo patronictl -c /etc/patroni/patroni.yml list

etcd witness / HA infrastructure:
- sudo systemctl status etcd

Zabbix Server:
- sudo systemctl status zabbix-server

Zabbix Proxy:
- sudo systemctl status zabbix-proxy

Zabbix Agent 2:
- sudo systemctl status zabbix-agent2

NGINX:
- sudo systemctl status nginx
- sudo systemctl status php-fpm

11.7 Log Review

Review Patroni:
- sudo journalctl -u patroni --since "1 hour ago"

etcd:
- sudo journalctl -u etcd --since "1 hour ago"

Keepalived:
- sudo journalctl -u keepalived --since "1 hour ago"

Zabbix Server:
- sudo tail -100 /var/log/zabbix/zabbix_server.log

Zabbix Proxy:
- sudo tail -100 /var/log/zabbix/zabbix_proxy.log

NGINX:
- sudo tail -100 /var/log/nginx/error.log

Confirm there are no unresolved critical errors.

11.8 Final Environment State

Capture the final PostgreSQL/Patroni state:
- sudo patronictl -c /etc/patroni/patroni.yml list

Expected:
- 1 Leader.
- 1 Replica.
- Cluster healthy.

Capture etcd health:
- sudo etcdctl \
    --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 \
    endpoint health

Expected:
- Three healthy etcd members.
- Quorum established.

Verify PostgreSQL VIP:
- ip addr

Expected:
- 10.90.5.12 assigned to the current PostgreSQL Primary.

Verify PostgreSQL connectivity:
- nc -zv 10.90.5.12 5432

Verify Zabbix Server HA:
- 1 Active.
- 1 Standby.

Verify all required Zabbix Proxies:
- Online.

Verify monitored hosts are receiving data normally.

11.9 Change Closure Criteria

The main Zabbix production deployment change can be considered successfully completed when:
- Zabbix Server HA is operational.
- Zabbix Server reports 1 Active + 1 Standby.
- PostgreSQL HA reports 1 Leader + 1 Replica.
- PostgreSQL automatic failover infrastructure is available through the completed Patroni/etcd change.
- PostgreSQL VIP 10.90.5.12 is assigned to the current Primary.
- Zabbix Server can connect to PostgreSQL through the PostgreSQL VIP.
- Zabbix Server HA failover has been successfully tested.
- Recovered Zabbix Server rejoins as Standby.
- Zabbix Proxies are Online.
- Zabbix monitoring data continues normally.
- NGINX HTTPS is operational for https://nms-us.belcan.com.
- TLS certificate validation is successful.
- Zabbix database backup has been successfully created and validated.
- Proxy database backups have been successfully created and validated.
- Zabbix Server, Zabbix Proxy and NGINX configurations have been backed up.
- Required backups have been transferred to the approved enterprise backup repository.
- No unresolved critical errors exist in Zabbix Server, Zabbix Proxy, NGINX or PostgreSQL integration logs.
- Final HA and application state has been documented.

11.10 Change Documentation

Document the final production state, including:
- Zabbix Server Active/Standby roles.
- PostgreSQL Leader/Replica roles.
- PostgreSQL VIP.
- Zabbix Server VIP.
- NGINX production hostname.
- Proxy status by region.
- Backup location.
- Results of Zabbix HA failover testing.
- Reference to the completed PostgreSQL Automatic Failover change request.
- Any deviations or issues encountered during implementation and their resolution.
