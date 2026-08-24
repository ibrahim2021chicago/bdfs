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


6.3 Open the Zabbix frontend and complete the Zabbix Web Installer:

- http://<nginx_server_ip>/

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

8.1 PostgreSQL /Patroni / etcd Connectivity:

Validate connectivity between all three nodes, run from each node munmssql01, cgnmssql01 & munmsetcd01:
- nc -zv 10.90.5.3 2379
- nc -zv 10.90.5.4 2379
- nc -zv 10.90.5.27 2379

Validate etcd cluster health:
- sudo etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health
- sudo etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 member list


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


8.4 PostgreSQL Connectivity:

Validate PostgreSQL through the PostgreSQL VIP:
- nc -zv 10.90.5.12 5432

Verify the current primary:
- sudo -u postgres psql
- \c zabbix
- SELECT pg_is_in_recovery();

Expected on the current primary:
f

On the standby:
t


8.5 Zabbix Server Connectivity:

Validate Zabbix Server port using Zabbix Server VIP:
- nc -zv 10.90.5.11 10051


8.6 Proxy Connectivity:

For each active Zabbix Proxy:
- nc -zv 10.90.5.11 10051

Verify the proxy database and schema exists:
- psql -h 127.0.0.1 -U zabbix_proxy_cg -d zabbix_proxy_cg
- \dt


8.7 Agent Connectivity:

Verify agent 2 status:
- sudo systemctl status zabbix-agent2
- ss -lntp | grep 10050


8.8 Functional Validation:

Log in to the Zabbix UI and Verify:
- Zabbix UI accessible through NGINX HTTPS
- Zabbix Server nodes configured correctly
- Zabbix Server HA status shows 1 Active / 1 Standby
- PostgreSQL cluster shows 1 Leader / 1 Replica
- Proxies show Online
- Hosts show Available /Green
- Latest data is being received
- No unexpected database or proxy errors





9. Failover Testing

9.1 PostgreSQL Automatic Failover - Patroni Failure Test

9.1.1 Record current cluster state

Run on either PostgreSQL node:
- sudo patronictl -c /etc/patroni/patroni.yml list

Record:
Current Leader
Current Replica
Cluster state
PostgreSQL VIP location

Verify the VIP:
- ip addr


9.1.2 Verify etcd cluster health

Before testing failover:
- sudo etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health

Verify all three etcd members are healthy.

Also verify membership:
- sudo etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 member list

Expected:
3 etcd members
Healthy quorum


9.1.3 Simulate Patroni failure

On the current PostgreSQL Primary:
- sudo systemctl stop patroni

Do not manually promote PostgreSQL using "pg_ctl promote".

This test validates that the surviving Patroni node detects loss of the active Patroni leader and performs automatic promotion using etcd as the DCS.


9.1.4 Verify automatic PostgreSQL promotion

On the surviving PostgreSQL node:
- sudo patronictl -c /etc/patroni/patroni.yml list

Expected:
munmssql01          Replica
cgnmssql01            Leader

assuming munmssql01 was the original Primary.

Verify the newly promoted Primary:
- sudo -u postgres psql -c "SELECT pg_is_in_recovery();"

Expected:
f

This confirms that the node is operating as Primary.


9.1.5 Verify PostgreSQL VIP movement

Verify the PostgreSQL VIP has moved to the new Primary:
- ip addr

Test PostgreSQL connectivity through the VIP:
- nc -zv <POSTGRESQL_VIP> 5432

Connect through the VIP:
- psql -h <POSTGRESQL_VIP> -U <zabbix_db_user> -d <zabbix_db>

Verify:
- SELECT pg_is_in_recovery();

Expected:
f



9.2 PostgreSQL complete Node Failure Test

After successfully completing the Patroni failure test and restoring the original node, perform a controlled complete PostgreSQL node failure simulation.

On the current Primary:
- sudo shutdown -h now

This simulates complete loss of the PostgreSQL VM rather than simply stopping PostgreSQL or Patroni.

Expected failover sequence:

Primary PostgreSQL node fails
                                  ⇩
Patroni on surviving node detects Primary failure
                                  ⇩
etcd confirms loss of leader lease
                                  ⇩
Patroni promotes surviving Replica
                                  ⇩
Keepalived moves PostgreSQL VIP
                                  ⇩
Applications reconnect through PostgreSQL VIP


Verify from the surviving PostgreSQL node:
- sudo patronictl -c /etc/patroni/patroni.yml list

Confirm the surviving node is:
Leader

Verify:
- sudo -u postgres psql -c "SELECT pg_is_in_recovery();"

Expected:
f

Verify the PostgreSQL VIP:
- ip addr

and:
- nc -zv <POSTGRESQL_VIP> 5432



9.3 PostgreSQL Node Recovery/Rejoin

Restore the failed PostgreSQL node.

Verify Patroni:
- sudo systemctl status Patroni

Verify cluster state:
- sudo patronictl -c /etc/patroni/patroni.yml list

The recovered node should rejoin the cluster as a Replica.

Expected:
cgnmssql01            Leader
munmssql01          Replica

Verify the recovered node:
- sudo -u postgres psql -c "SELECT pg_is_in_recovery();"

Expected:
t

Do not manually promote the recovered node.

If leadership needs to be moved back to the recovered node, perform a controlled Patroni switchover.



9.4 PostgreSQL controlled switchover test

Once both PostgreSQL nodes are healthy:
- sudo patronictl -c /etc/patroni/patroni.yml list

Perform a controlled switchover:
- sudo patronictl -c /etc/patroni/patroni.yml switchover

Select the appropriate target node.

Verify:
- sudo patronictl -c /etc/patroni/patroni.yml list

Confirm:
- Intended node becomes Leader
- Previous Primary becomes Replica
- PostgreSQL VIP moves to the new Primary
- Applications can connect through the same VIP



9.5 Zabbix Server HA Failover Test

Verify the initial Zabbix HA state:
1 Active
1 Standby

Identify the current Active Zabbix Server node.

On the Active node:
- sudo systemctl stop zabbix-server

Verify in the Zabbix UI that the Standby node automatically becomes Active.

Confirm:
- Zabbix UI remains accessible
- New Active Zabbix Server is operational
- Hosts continue reporting data
- Proxies remain online
- No critical errors are generated



9.6 Zabbix Server Recovery

On the stopped Zabbix Server:
- sudo systemctl start zabbix-server

Verify:
- sudo systemctl status zabbix-server

Confirm in the Zabbix UI that the recovered server rejoins the HA cluster as Standby.

Verify the cluster again shows:
1 Active
1 Standby



9.7 End-to-End HA Failover Validation

Perform final validation after completing the PostgreSQL and Zabbix HA tests.

Verify the complete workflow:

PostgreSQL Primary Failure
                                  ⇩
Patroni detects failure
                                  ⇩
etcd validates leader election
                                  ⇩
Standby PostgreSQL promoted
                                  ⇩
Keepalived moves PostgreSQL VIP
                                  ⇩
Zabbix Server reconnects
                                  ⇩
Zabbix monitoring continues
                                  ⇩
Proxies remain online
                                  ⇩
Hosts continue reporting data

Record:
- Failure initiation time
- Patroni failure detection time
- PostgreSQL promotion time
- VIP movement time
- Application recovery time
- Zabbix monitoring recovery time
- Any monitoring/data gap
- Errors observed in logs



9.8 Failover Test Success Criteria

The failover test will be considered successful when Patroni automatically detects:
- PostgreSQL Primary failure
- etcd maintains quorum and supports leader election.
- Replica is automatically promoted to Primary.
- No manual pg_ctl promote is required.
- PostgreSQL VIP moves to the new Primary.
- Applications reconnect using the same PostgreSQL VIP.
- Failed PostgreSQL node successfully rejoins as Replica.
- No split-brain condition occurs.
- Zabbix Server HA successfully changes Active/Standby roles.
- Zabbix Proxies remain online.
- Monitoring data continues to be collected.
- No critical errors remain in Patroni, etcd, PostgreSQL, Keepalived, Zabbix Server, or Zabbix Proxy logs.







10. Backup and Configuration Protection

10.1 PostgreSQL Zabbix Database Backup

Run the backup from the designated backup server, or from an approved PostgreSQL/utility server that has network access to the PostgreSQL VIP.

The backup connects to the PostgreSQL VIP, which always points to the current Primary.

Verify VIP connectivity:
- nc -zv <POSTGRESQL_VIP> 5432

Perform the backup:
- pg_dump \
                  -h <POSTGRESQL_VIP> \
                  -U <zabbix_db_user> \
                 -d <zabbix_db> \
                  -Fc \
                  -f /backup/zabbix/zabbix_$(date +%Y%m%d_%H%M%S).dump

Verify & validate the dump:
- ls -lh /backup/zabbix/
- pg_restore --list /backup/zabbix/<backup-file>.dump



10.2 PostgreSQL Proxy Database Backup

Each Zabbix Proxy has its own PostgreSQL database.

Run on each proxy server:
- mkdir -p /backup/zabbix-proxy
- pg_dump \
                  -h 127.0.0.1 \
                  -U <zabbix_proxy_user> \
                 -d <zabbix_proxy_db> \
                  -Fc \
                  -f /backup/zabbix-proxy/zabbix_proxy_<region>_$(date +%Y%m%d_%H%M%S).dump

Validate:
- pg_restore --list /backup/zabbix-proxy/<backup-file>.dump


Proxy database backups should also be transferred to the approved enterprise backup repository.




10.3 Patroni Configuration Backup

Run on both PostgreSQL nodes:

Create backup:
- sudo tar -czf \
                  /backup/patroni_config_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
                  /etc/patroni/

Verify:
- ls -lh /backup/patroni_config_*

Protect the backup because Patroni configuration may contain database/replication credentials:
- sudo chmod 600 /backup/patroni_config_*.tar.gz




10.4 etcd Configuration backup

Run on all three etcd members:
- munmssql01
- cgnmssql01
- munmsetcd01

Backup the etcd configuration:
- sudo tar -czf \
                  /backup/etcd_config_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
                  /etc/etcd/

Verify:
- ls -lh /backup/etcd_config_*

Also capture the systemd configuration if customized:
- sudo systemctl cat etcd > \
                  /backup/etcd_systemd_$(hostname)_$(date +%Y%m%d_%H%M%S).txt




10.5 etcd Data Snapshot

Run from one healthy etcd member, preferably the designated etcd management/backup node.

Create a snapshot:
- sudo mkdir -p /backup/etcd
- sudo etcdctl --endpoints=http://10.90.5.3:2379 \
                               snapshot save \
                               /backup/etcd/etcd_$(date +%Y%m%d_%H%M%S).db

Verify the snapshot:
- sudo etcdctl \
              snapshot status \
              /backup/etcd/<snapshot-file>.db

The etcd snapshot protects the Patroni DCS state. It is complementary to the PostgreSQL database backup and is not a replacement for it.



10.6 Keepalived Configuration Backup

Run on both PostgreSQL nodes:
- sudo tar -czf \
                  /backup/keepalived_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
                  /etc/keepalived/

Verify:
- ls -lh /backup/keepalived_*




10.7 Zabbix Server Configuration Backup

Run on both Zabbix Server nodes:
- sudo tar -czf \
                  /backup/zabbix_server_config_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
                  /etc/zabbix/

Verify:
- ls -lh /backup/zabbix_server_config_*




10.8 Zabbix Proxy Configuration Backup

Run on each Zabbix Proxy:
- sudo tar -czf \
                  /backup/zabbix_proxy_config_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
                  /etc/zabbix/

Protect the backup:
- sudo chmod 600 /backup/zabbix_proxy_config_*.tar.gz



10.9 NGINX Configuration and TLS Backup

Run on each NGINX server:
- sudo tar -czf \
                  /backup/nginx_config_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
                  /etc/nginx/

Backup the certs/keys:
- sudo tar -czf \
                  /backup/zabbix_certs_$(hostname)_$(date +%Y%m%d_%H%M%S).tar.gz \
                  /etc/zabbix/certs/

Protect the backup:
- sudo chmod 600 /backup/zabbix_certs_*.tar.gz




10.10 Backup Verification and Transfer

After completing the backups:
- df -h /backup

List the backup files:
- find /backup -type f -ls

Verify that the expected backups exist:
- Zabbix PostgreSQL database
- Proxy PostgreSQL databases
- Patroni configuration
- etcd configuration
- etcd snapshot
- Keepalived configuration
- Zabbix Server configuration
- Zabbix Proxy configuration
- NGINX configuration
- TLS Certificates/Keys

Transfer the backups from the local staging location to the organization's approved enterprise backup repository.

The local /backup directory should be considered temporary staging unless it is explicitly part of the organization's backup infrastructure.






11 Security Hardening, Validation and Change Closure

11.1 PostgreSQL Network Security

Verify PostgreSQL listeners:
- sudo ss -lntp | grep 5432

Review PostgreSQL access rules:
- sudo cat /var/lib/pgsql/data/pg_hba.conf

Ensure PostgreSQL access is restricted to the required:
- Zabbix Server nodes
- PostgreSQL HA nodes
- Approved application networks
- Required administrative/monitoring sources

Avoid unnecessarily broad rules such as:
0.0.0.0/0

unless explicitly required and approved.



11.2 etcd Security

Verify etcd listeners:
- sudo ss -lntp | grep -E '2379|2380'

The ports are:
2379 -> etcd client/API
2380 - etcd peer-to-peer communication

Restrict firewall access so that only the required Patroni/etcd nodes can communicate on these ports.



11.3 Patroni REST API Security

Verify Patroni REST API:
- sudo ss -lntp | grep 8008

Restrict access to trusted HA/management systems.

Do not expose the Patroni REST API unnecessarily to the wider production network.

Test locally:
- curl http://127.0.0.1:8008/patroni




11.4 PostgreSQL HA / Keepalived Validation

On both PostgreSQL nodes:
- sudo systemctl status patroni
- sudo systemctl status keepalived

Check the cluster:
- sudo patronictl -c /etc/ patroni/patroni.yml list

Expected:
1 Leader
1 Replica

Check VIP ownership:
- ip addr

The PostgreSQL VIP must be assigned to the current Primary.

Test:
- nc -zv <POSTGRESQL_VIP> 5432




11.5 Zabbix Server HA Validation

On both Zabbix Server nodes:
- sudo systemctl status zabbix-server

Verify in the Zabbix UI:
1 Active
1 Standby

Perform the final HA status check after all failover testing is complete.




11.6 Zabbix Proxy Validation

On each Proxy:
- sudo systemctl status zabbix-proxy
- sudo systemctl status zabbix-agent2

Verify proxy connectivity to the Zabbix Server:
- nc -zv <ZABBIX_SERVER_VIP> 10051

In the Zabbix UI:
Data collection -> Proxies

Confirm each required proxy shows:
Online



11.7 NGINX /HTTPS Validation

On the NGINX server:
- sudo nginx -t

Expected:
- syntax is ok
- test is successful

Verify:
- sudo systemctl status nginx
- sudo systemctl status php-fpm

Test the production hostname:
- curl -I http://nms-us.belcan.com

Confirm HTTP redirects to HTTPS.

Then:
- curl -vk https://nms-us.belcan.com

Verify the certificate:
- openssl s_client \
               -connect nms-us.belcan.com:443 \
               -servername nms-us.belcan.com </dev/null 2>/dev/null \
               | openssl x509 -noout -subject -issuer -dates

Confirm:
Subject/SAN = nms-us.belcan.com

and the certificate is within its validity period.



11.8 Service and Log Validation

PostgreSQL/Patroni nodes
- sudo systemctl status patroni
- sudo systemctl status keepalived
- sudo patronictl -c /etc/patroni/patroni.yml list

etcd witness:
- sudo systemctl status etcd

Zabbix Server:
- sudo systemctl status zabbix-server

Zabbix Proxy:
- sudo systemctl status zabbix-proxy

Zabbix Agent2:
- sudo systemctl status zabbix-agent2

NGINX:
- sudo systemctl status nginx
- sudo systemctl status php-fpm



11.9 Log Review

Review Patroni:
- sudo journalctl -u patroni --since "1 hour ago"

etcd:
- sudo journalctl -u etcd--since "1 hour ago"

Keepalived:
- sudo journalctl -u keepalived--since "1 hour ago"

Zabbix Server:
- sudo tail -100 /var/log/zabbix/zabbix_server.log

Zabbix Proxy:
- sudo tail -100 /var/log/zabbix/zabbix_proxy.log

NGINX:
- sudo tail -100 /var/log/nginx/error.log

Confirm there are no unresolved critical errors.



11.11 Change Closure Criteria

The change can be considered successfully completed when:
- PostgreSQL HA is operation with Patroni.
- All three etcd members are healthy and quorum is established.
- PostgreSQL reports 1 Leader + 1 Replica.
- PostgreSQL is assigned to the current Primary.
- Patroni automatic failover has been successfully tested.
- Complete PostgreSQL node failure has been successfully tested.
- Failed PostgreSQL node successfully rejoins as Replica.
- Controlled PostgreSQL switchover has been successfully tested.
- Zabbix Server Active/Standby failover has been successfully tested.
- Zabbix Proxies are Online.
- NGINX HTTPS is operation for "nms-us.belcan.com".
- Zabbix monitoring data continues normally.
- Zabbix database backup has been successfully created and validated.
- Proxy database backup has been successfully created and validated.
- Patroni, etcd, Keepalived, Zabbix and NGINX configurations have been backed up.
- etcd snapshot has been successfully created and validated.
- Backups have been transferred to the approved enterprise backup repository.
- No unresolved critical errors exist in Patroni, etcd, PostgreSQL, Keepalived, Zabbix Server, Zabbix Proxy or NGINX logs.





