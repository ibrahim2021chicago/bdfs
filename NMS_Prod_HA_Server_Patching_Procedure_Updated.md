# NMS Production HA Server Patching Procedure

## 1. Patching Sequence

Patch the NMS Production environment **one server at a time**:

1. **Muhlhauser**
2. **Congressional**

### HA Rules

- Never patch both PostgreSQL/Patroni nodes at the same time.
- Never patch more than one etcd member at the same time.
- Validate the HA state after every reboot before proceeding.
- Automatic PostgreSQL failover is already implemented using **Patroni + etcd**. The current Patroni Leader may therefore be patched/rebooted directly.
- Patroni will detect the unavailable node and promote the healthy Replica.
- Keepalived will move PostgreSQL VIP `10.90.5.12` to the new Patroni Leader.

---

# 2. Muhlhauser Patching

Patch Muhlhauser servers first, one at a time.

## 2.1 munmssql01 – PostgreSQL / Patroni / Keepalived / etcd

### Before patching

Check services:

```bash
systemctl status patroni
systemctl status keepalived
systemctl status etcd
```

Check Patroni:

```bash
patronictl -c /etc/patroni/patroni.yml list
```

Check etcd:

```bash
etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health
```

Check VIP:

```bash
ip addr | grep 10.90.5.12
```

### Patch and reboot

Apply approved OS patches and reboot:

```bash
reboot
```

### After reboot

```bash
systemctl status patroni
systemctl status keepalived
systemctl status etcd
```

```bash
patronictl -c /etc/patroni/patroni.yml list
```

Confirm:

- [ ] Node returned to the Patroni cluster.
- [ ] PostgreSQL role is correct.
- [ ] Replication is healthy.
- [ ] Keepalived is running.
- [ ] VIP is owned by the current Patroni Leader.

---

## 2.2 munmsetcd01 – etcd

### Before patching

```bash
systemctl status etcd
```

```bash
etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health
```

Patch and reboot:

```bash
reboot
```

### After reboot

```bash
systemctl status etcd
```

```bash
etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health
```

Confirm:

- [ ] etcd member is healthy.
- [ ] All three etcd endpoints are healthy.
- [ ] Quorum is available.

---

## 2.3 Muhlhauser Zabbix Server

### Before and after patching

Check:

```bash
systemctl status zabbix-server
systemctl status zabbix-agent2
```

Patch and reboot the server.

After reboot, confirm:

- [ ] Zabbix Server running.
- [ ] Zabbix Agent 2 running.
- [ ] Zabbix HA status healthy.
- [ ] Monitoring data updating.
- [ ] No database connection error.

---

## 2.4 Muhlhauser NGINX Server

### Before patching

```bash
systemctl status nginx
systemctl status php-fpm
systemctl status zabbix-agent2
nginx -t
```

Patch and reboot.

### After reboot

```bash
systemctl status nginx
systemctl status php-fpm
systemctl status zabbix-agent2
```

Confirm:

- [ ] NGINX running.
- [ ] PHP-FPM running.
- [ ] Zabbix URL accessible.
- [ ] Login/dashboard accessible.
- [ ] No database connection error.

---

## 2.5 Muhlhauser Proxy Server(s)

### Before patching

```bash
systemctl status zabbix-proxy
systemctl status zabbix-agent2
```

Patch and reboot.

### After reboot

```bash
systemctl status zabbix-proxy
systemctl status zabbix-agent2
```

Confirm:

- [ ] Proxy available in Zabbix UI.
- [ ] Hosts monitored through the proxy are reporting data.

---

# 3. Congressional Patching

Start Congressional **only after all Muhlhauser servers have been patched and validated**.

Patch Congressional servers one at a time.

> **Note:** `cgnmssql01` is both a PostgreSQL/Patroni node and an etcd member. Therefore, its Patroni, Keepalived and etcd checks are performed together. There is no separate Congressional etcd patching step for this server.

## 3.1 cgnmssql01 – PostgreSQL / Patroni / Keepalived / etcd

### Before patching

Check services:

```bash
systemctl status patroni
systemctl status keepalived
systemctl status etcd
```

Check Patroni:

```bash
patronictl -c /etc/patroni/patroni.yml list
```

Check etcd:

```bash
etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health
```

Patch and reboot:

```bash
reboot
```

### After reboot

```bash
systemctl status patroni
systemctl status keepalived
systemctl status etcd
```

Validate Patroni:

```bash
patronictl -c /etc/patroni/patroni.yml list
```

Validate etcd:

```bash
etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health
```

Confirm:

- [ ] Patroni healthy.
- [ ] PostgreSQL role is correct.
- [ ] Replication is streaming.
- [ ] Keepalived healthy.
- [ ] VIP is on the current Patroni Leader.
- [ ] cgnmssql01 etcd member is healthy.
- [ ] All etcd members remain healthy.

---

## 3.2 Congressional Zabbix Server

### Before and after patching

Check:

```bash
systemctl status zabbix-server
systemctl status zabbix-agent2
```

Patch and reboot.

After reboot, confirm:

- [ ] Zabbix Server running.
- [ ] Zabbix Agent 2 running.
- [ ] Zabbix HA status healthy.
- [ ] Monitoring data updating.
- [ ] No critical errors.

---

## 3.3 Congressional NGINX Server

### Before patching

```bash
systemctl status nginx
systemctl status php-fpm
systemctl status zabbix-agent2
nginx -t
```

Patch and reboot.

### After reboot

```bash
systemctl status nginx
systemctl status php-fpm
systemctl status zabbix-agent2
```

Confirm:

- [ ] NGINX running.
- [ ] PHP-FPM running.
- [ ] Zabbix URL accessible.
- [ ] Frontend functional.

---

## 3.4 Congressional Proxy Server(s)

### Before patching

```bash
systemctl status zabbix-proxy
systemctl status zabbix-agent2
```

Patch and reboot.

### After reboot

```bash
systemctl status zabbix-proxy
systemctl status zabbix-agent2
```

Confirm:

- [ ] Proxy available in Zabbix UI.
- [ ] Monitoring data received.

---

# 4. Final NMS Production Validation

## PostgreSQL / Patroni

```bash
patronictl -c /etc/patroni/patroni.yml list
```

- [ ] One Leader.
- [ ] One Replica.
- [ ] Replica streaming.
- [ ] No abnormal replication lag.

## etcd

```bash
etcdctl --endpoints=http://10.90.5.3:2379,http://10.90.5.4:2379,http://10.90.5.27:2379 endpoint health
```

- [ ] All three members healthy.
- [ ] Quorum available.

## PostgreSQL VIP

```bash
ip addr | grep 10.90.5.12
```

- [ ] VIP assigned to current Patroni Leader.

## Zabbix / NGINX / Proxies

- [ ] Zabbix UI accessible.
- [ ] Zabbix HA healthy.
- [ ] NGINX healthy.
- [ ] All required proxies connected.
- [ ] Monitoring data updating.
- [ ] No database connection errors.
- [ ] No critical service failures.

## Final Sign-off

- [ ] Muhlhauser patching completed successfully.
- [ ] Congressional patching completed successfully.
- [ ] PostgreSQL/Patroni HA healthy.
- [ ] etcd cluster healthy.
- [ ] Keepalived/VIP healthy.
- [ ] Zabbix monitoring healthy.
- [ ] NMS Production operational.
