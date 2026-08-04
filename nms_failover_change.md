1. Pre-Implementation Activities

1.1 Infrastructure Validation

Validate the new Witness VM configuration:
Rocky Linux 9
2 vCPU
4 GB RAM
Default disk allocation ( no additional storage required)
Network Interface - 10.90.5.0/24 (VLAN 5)

Validate hostname resolution and network reachability between:
munmssql01
cgnmssql01
Witness VM


1.2 Updates & Setup (All Nodes):

- sudo dnf update -y
- Run ansible r9-common role to install all Belcan-specific configs


2. Deploy etcd cluster

2.1 Configure hostname resolution

Verify connectivity between all cluster members:
- ping munmssql01
- ping cgnmssql01
- ping munmsetcd01

- getent hosts munmssql01
- getent hosts cgnmssql01
- getent hosts munmsetcd01

If DNS is unavailable, update /etc/hosts on all three servers


2.2 Install PGDG Repository:
- sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm

Disable all PostgreSQL server repositories:

Edit /etc/yum.repos.d/pgdg-redhat-all.repo

[pgdg14]
enabled=0

[pgdg15]
enabled=0

[pgdg16]
enabled=0

[pgdg17]
enabled=0

[pgdg18]
enabled=0

Only leave the common/extra repositories available.

Enable the PGDG extras repository:
- sudo dnf config-manager --enable pgdg-rhel9-extras
- sudo dnf clean all
- sudo dnf makecache

Verify:
- sudo dnf repolist | grep pgdg

Expected output:
pgdg-common
pgdg-rhel9-extras


2.3 Install etcd

Run on all nodes:
- munmssql01
- cgnmssql01
- munmsetcd01

- sudo dnf install -y etcd
- etcd --version


2.4 Configure etcd cluster

Edit the configuration file /etc/etcd/etcd.conf


munmssql01:
ETCD_NAME="munmssql01"
ETCD_DATA_DIR="/var/lib/etcd/default.etcd"
ETCD_LISTEN_PEER_URLS="http://10.90.5.3:2380"
ETCD_LISTEN_CLIENT_URLS="http://10.90.5.3:2379,http://127.0.0.1:2379"
ETCD_INITIAL_ADVERTISE_PEER_URLS="http://10.90.5.3:2380"
ETCD_INITIAL_CLUSTER="munmssql01=http://10.90.5.3:2380,cgnmssql01=http://10.90.5.4:2380,munmsetcd01=http://10.90.5.27:2380"
ETCD_INITIAL_CLUSTER_STATE="new"
ETCD_INITIAL_CLUSTER_TOKEN="postgres-ha"
ETCD_ADVERTISE_CLIENT_URLS="http://10.90.5.3:2379"
ETCD_ENABLE_V2="true"



cgnmssql01:
ETCD_NAME="cgnmssql01"
ETCD_DATA_DIR="/var/lib/etcd/default.etcd"
ETCD_LISTEN_PEER_URLS="http://10.90.5.4:2380"
ETCD_LISTEN_CLIENT_URLS="http://10.90.5.4:2379,http://127.0.0.1:2379"
ETCD_INITIAL_ADVERTISE_PEER_URLS="http://10.90.5.4:2380"
ETCD_INITIAL_CLUSTER="munmssql01=http://10.90.5.3:2380,cgnmssql01=http://10.90.5.4:2380,munmsetcd01=http://10.90.5.27:2380"
ETCD_INITIAL_CLUSTER_STATE="new"
ETCD_INITIAL_CLUSTER_TOKEN="postgres-ha"
ETCD_ADVERTISE_CLIENT_URLS="http://10.90.5.4:2379"
ETCD_ENABLE_V2="true"



munmsetcd01:

ETCD_NAME="munmsetcd01"
ETCD_DATA_DIR="/var/lib/etcd/default.etcd"
ETCD_LISTEN_PEER_URLS="http://10.90.5.27:2380"
ETCD_LISTEN_CLIENT_URLS="http://10.90.5.27:2379,http://127.0.0.1:2379"
ETCD_INITIAL_ADVERTISE_PEER_URLS="http://10.90.5.27:2380"
ETCD_INITIAL_CLUSTER="munmssql01=http://10.90.5.3:2380,cgnmssql01=http://10.90.5.4:2380,munmsetcd01=http://10.90.5.27:2380"
ETCD_INITIAL_CLUSTER_STATE="new"
ETCD_INITIAL_CLUSTER_TOKEN="postgres-ha"
ETCD_ADVERTISE_CLIENT_URLS="http://10.90.5.27:2379"
ETCD_ENABLE_V2="true"



2.5 Enable and start etcd:
- sudo systemctl enable --now etcd


2.6 Validate etcd Cluster

Run from any node:
- etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 member list
- etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health

All members should report healthy.



3. Install Patroni

3.1 Install Patroni Packages

Perform on:
- munmssql01
- cgnmssql01

- sudo dnf install -y patroni patroni-etcd
- patroni --version


3.2 Configure Patroni

Configuration file:
/etc/patroni/patroni.yml

- Configuration files are attached for both munmssql01 and cgnmssql01


3.3 Enable Patroni
- sudo systemctl enable patroni

Do not start the service until the configuration has been validated.


3.4 Validate Patroni Configuration
- patroni --validate-config /etc/patroni/patroni.yml

Resolve any validation errors before proceeding.


3.4 Start Patroni on both PostgreSQL servers:
- sudo systemctl start patroni


3.5 Validate Patroni Cluster
- patronictl -c /etc/patroni/patroni.yml list

Expected output:
+ Cluster: zabbix-prod-us (7655714789609877365) ----+-------------+-----+------------+-----+
|   Member   |    Host   |   Role  |   State   | TL | Receive LSN | Lag | Replay LSN | Lag |
+------------+-----------+---------+-----------+----+-------------+-----+------------+-----+
| cgnmssql01 | 10.90.5.4 | Replica | streaming |  8 |  1/F34D3138 |   0 | 1/F34D3138 |   0 |
| munmssql01 | 10.90.5.3 | Leader  | running   |  8 |             |     |            |     |
+------------+-----------+---------+-----------+----+-------------+-----+------------+-----+


3.6 Perform Switchover Validation

Run:
- patronictl -c /etc/patroni/patroni.yml switchover

Verify:
- patronictl -c /etc/patroni/patroni.yml list

Confirm:
- Replica becomes Leader.
- Previous Leader becomes Replica.
- Replication resumes successfully.
- Timeline increments.
- Cluster remains healthy.



4. Keepalived Integration

4.1 Configure Patroni Health Checks

Create the health check script on both servers:
- munmssql01
- cgnmssql01

/usr/local/bin/check_patroni.sh

=================================================================================
#!/bin/bash

STATUS=$(curl --noproxy '*' -s -o /dev/null -w "%{http_code}" http://$(hostname -I | awk '{print $1}'):8008/primary)

[ "$STATUS" = "200" ]
================================================================================= 

Grant execution permission:
- sudo chmod +x /usr/local/bin/check_patroni.sh


4.2 Configure Keepalived

Configuration file:
/etc/keepalived/keepalived.conf


munmssql01
=========================================
global_defs {
    router_id MU_PGSQL
}

vrrp_script chk_patroni {
    script "/usr/local/bin/check_patroni.sh"
    interval 2
    timeout 2
    fall 2
    rise 2
    weight -250
}

vrrp_instance VI_PG {
    state BACKUP
    interface ens33
    virtual_router_id 51
    priority 200
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass BelcanVIP
    }

    virtual_ipaddress {
        10.90.5.12/24
    }

    track_script {
        chk_patroni
    }
}
=========================================


cgnmssql01
=========================================
global_defs {
    router_id CG_PGSQL
}

vrrp_script chk_patroni {
    script "/usr/local/bin/check_patroni.sh"
    interval 2
    timeout 2
    fall 2
    rise 2
    weight -250
}

vrrp_instance VI_PG {
    state BACKUP
    interface ens33
    virtual_router_id 51
    priority 150
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass BelcanVIP
    }

    virtual_ipaddress {
        10.90.5.12/24
    }

    track_script {
        chk_patroni
    }
}
=========================================


4.3 Restart kepalived:
- sudo systemctl restart keepalived

Validate:
- systemctl status keepalived
- ip addr | grep 10.90.5.12

Expected:
- VIP assigned only to Patroni leader
- Replica does not own the VIP




5 End-to-End HA Validation

5.1 Validate PostgreSQL Connectivity via VIP

From Zabbix Server:
- nc -zv 10.90.5.12 5432

or
- psql -h 10.90.5.12 -U zabbix -d zabbix

Expected:
- Successful database connection.


5.2 Validate Zabbix Frontend

Access:
http://<zabbix-url>

Verify:
- Frontend accessible.
- Dashboard loads.
- No database connection errors.
 -Latest monitoring data updating.


5.3 Validate PostgreSQL Replication

On current Leader:
- SELECT application_name, client_addr, state, sync_state FROM pg_stat_replication;

Expected:
state = streaming


5.4 Validate etcd Cluster

- etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 member list
- etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health

Expected:
- All members healthy.
- No alarms.


5.5 Validate Patroni Cluster
- patronictl -c /etc/patroni/patroni.yml list
- patronictl -c /etc/patroni/patroni.yml history

Expected:
- One Leader.
- One Replica.
- Cluster healthy.
- Timeline incremented after switchover.




6. Post-Implementation Validation

Verify:
- Patroni service
- Keepalived service
- etcd service
- PostgreSQL service (managed by Patroni)
- VIP ownership
- Zabbix Server
- NGINX
- Zabbix Fronted
- Database replication
- Patroni cluster health
- Monitoring data collection
- No critical errors in system logs

