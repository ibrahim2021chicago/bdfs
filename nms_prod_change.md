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
- CREATE ROLE zabbix_proxy_<region> LOGIN;
- \password zabbix_proxy_<region>
- CREATE DATABASE zabbix_proxy_<region> OWNER zabbix_proxy_<region>;
- \q


7.3 Import schema

- psql -h 127.0.0.1 -U zabbix_proxy_mu -d zabbix_proxy_mu -f /usr/share/zabbix-sql-scripts/postgresql/proxy.sql


7.4 Configure Proxy:

- ProxyMode=0
- Server=<zabbix_vip>
- Hostname=<proxy_server_name>
- DBHost=127.0.0.1
- DBName=zabbix_proxy_<region>
- DBUser=zabbix_proxy_<region>
- DBPassword=<password>


7.5 Start services:

- systemctl enable --now zabbix-proxy zabbix-agent2





7. Validation Plan

7.1 Connectivity Tests:

- nc -zv <db_vip> 5432
- nc -zv <zabbix_vip> 10051
- zabbix_get -s <agent_ip> -k agent.ping


7.2 Functional Validation:

- Login to Zabbix UI
- Verify:
    Hosts = GREEN
    Proxies connected
    Data ingestion working

- HA Status:
    1 Active node
    1 Standby node


8. Failover Testing

8.1 Database Failover:

- systemctl stop postgresql-15   # primary
- pg_ctl promote -D /var/lib/pgsql/15/data


8.2 Zabbix HA Failover:

- systemctl stop zabbix-server
- Verify secondary becomes active


9. Post-Implementation Tasks

9.1 Backup Configuration:

- pg_dump -h <db_vip> -U zabbix -Fc zabbix > /backup/zabbix.dump
- tar -czf /backup/zabbix_configs.tar.gz /etc/zabbix/


9.2 Security Hardening:

- Change default credentials
- Enable TLS for proxy/server communication
- Restrict DB access to CIDRs only
- Enable HTTPS on frontend


10. Validation & Closure Criteria

Change will be considered successful when:

- Zabbix UI accessible via NGINX
- PostgreSQL replication active
- Zabbix HA shows Active/Standby
- Proxies reporting data
- Failover successfully tested
- No critical alerts/errors in logs
