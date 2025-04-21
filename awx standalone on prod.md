Production-Ready AWX Deployment on a Single Rocky Linux 9.5 Server
For a production deployment of AWX on a single server, while maintaining your current architecture (single node, k3s, self-signed certs initially), you should implement several additional production-grade considerations. Here's what to modify/enhance in your current setup:

1. Enhanced Resource Allocation
For production workloads, increase your resource allocations:

yaml
# In your awx-demo.yaml, add/modify:
apiVersion: awx.ansible.com/v1beta1
kind: AWX
metadata:
  name: awx-prod
spec:
  service_type: ClusterIP
  hostname: rocky.local.com
  ingress_type: ingress
  ingress_tls_secret: awx-tls-secret
  postgres_storage_class: local-path
  postgres_storage_requirements:
    requests:
      storage: 10Gi
  task_resource_requirements:
    requests:
      cpu: "2"
      memory: "4Gi"
    limits:
      cpu: "4"
      memory: "8Gi"
  web_resource_requirements:
    requests:
      cpu: "1"
      memory: "2Gi"
    limits:
      cpu: "2"
      memory: "4Gi"
  postgres_resource_requirements:
    requests:
      cpu: "1"
      memory: "2Gi"
    limits:
      cpu: "2"
      memory: "4Gi"

2. Database Configuration
For production PostgreSQL:

yaml
# Add to your awx-demo.yaml:
spec:
  postgres_configuration_secret: awx-postgres-config
  postgres_storage_requirements:
    requests:
      storage: 20Gi  # Increased from 10Gi
    limits:
      storage: 30Gi
Create a PostgreSQL configuration secret:

kubectl create secret generic awx-postgres-config \
  --from-literal=postgresql_shared_buffers=1GB \
  --from-literal=postgresql_work_mem=32MB \
  --from-literal=postgresql_max_connections=200 \
  -n awx

3. Backup Strategy
Implement a robust backup solution:

For PostgreSQL:

# Create a cron job for daily backups
kubectl create -n awx -f - <<EOF
apiVersion: batch/v1beta1
kind: CronJob
metadata:
  name: awx-postgres-backup
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: postgres:13
            env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: awx-demo-postgres-configuration
                  key: password
            command:
            - /bin/sh
            - -c
            - |
              PGPASSWORD=\$POSTGRES_PASSWORD pg_dump -h awx-demo-postgres -U awx awx > /backup/awx-\$(date +\%Y\%m\%d).sql
            volumeMounts:
            - mountPath: /backup
              name: backup-volume
          restartPolicy: OnFailure
          volumes:
          - name: backup-volume
            persistentVolumeClaim:
              claimName: awx-postgres-backup
EOF

# Create backup PVC
kubectl create -n awx -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: awx-postgres-backup
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 20Gi
EOF

For AWX configuration:

# Create a script to backup AWX configuration
cat <<'EOF' > awx-backup.sh
#!/bin/bash
DATE=$(date +%Y%m%d)
BACKUP_DIR=/backups/awx-$DATE
mkdir -p $BACKUP_DIR

# Backup Kubernetes resources
kubectl get all -n awx -o yaml > $BACKUP_DIR/awx-resources.yaml
kubectl get secret awx-demo-admin-password -n awx -o yaml > $BACKUP_DIR/awx-secret.yaml
kubectl get secret awx-tls-secret -n awx -o yaml > $BACKUP_DIR/awx-tls-secret.yaml

# Backup AWX data
kubectl exec -n awx deployment/awx-demo-task -- awx-manage dumpdata > $BACKUP_DIR/awx-data.json

# Compress backup
tar czf /backups/awx-$DATE.tar.gz -C /backups awx-$DATE
rm -rf $BACKUP_DIR
EOF

chmod +x awx-backup.sh

# Create a cron job on the host
sudo cp awx-backup.sh /usr/local/bin/
(crontab -l 2>/dev/null; echo "0 1 * * * /usr/local/bin/awx-backup.sh") | crontab -
4. Monitoring and Logging
Prometheus and Grafana:
bash
# Install kube-prometheus-stack
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set grafana.adminPassword=admin
AWX-specific monitoring:
yaml
# Add to your awx-demo.yaml:
spec:
  # ...
  extra_volumes: |
    - name: awx-metrics
      emptyDir: {}
  extra_volume_mounts: |
    - name: awx-metrics
      mountPath: /var/lib/awx/metrics
  # ...
5. Security Hardening
Pod Security Policies:
bash
# Create a restricted PSP
kubectl apply -f - <<EOF
apiVersion: policy/v1beta1
kind: PodSecurityPolicy
metadata:
  name: restricted
spec:
  privileged: false
  allowPrivilegeEscalation: false
  requiredDropCapabilities:
    - ALL
  volumes:
    - 'configMap'
    - 'emptyDir'
    - 'projected'
    - 'secret'
    - 'downwardAPI'
    - 'persistentVolumeClaim'
  hostNetwork: false
  hostIPC: false
  hostPID: false
  runAsUser:
    rule: 'MustRunAsNonRoot'
  seLinux:
    rule: 'RunAsAny'
  supplementalGroups:
    rule: 'MustRunAs'
    ranges:
      - min: 1
        max: 65535
  fsGroup:
    rule: 'MustRunAs'
    ranges:
      - min: 1
        max: 65535
  readOnlyRootFilesystem: false
EOF
Network Policies:
bash
kubectl apply -n awx -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: awx-restrict-traffic
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: awx-demo
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app.kubernetes.io/component: awx-web
    ports:
    - protocol: TCP
      port: 8052
  egress:
  - to:
    - podSelector:
        matchLabels:
          app.kubernetes.io/component: postgres
    ports:
    - protocol: TCP
      port: 5432
EOF
6. Enhanced Ingress Configuration
yaml
# Update your awx-demo.yaml ingress section:
spec:
  ingress_annotations:
    kubernetes.io/ingress.class: traefik
    traefik.ingress.kubernetes.io/router.tls: "true"
    traefik.ingress.kubernetes.io/router.middlewares: awx-rate-limit@kubernetescrd
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/service.serverstransport: awx-tls@kubernetescrd
Add rate limiting middleware:

bash
kubectl apply -n awx -f - <<EOF
apiVersion: traefik.containo.us/v1alpha1
kind: Middleware
metadata:
  name: rate-limit
spec:
  rateLimit:
    average: 100
    burst: 50
EOF
7. Scheduled Maintenance Jobs
bash
# Create a job for AWX maintenance tasks
kubectl apply -n awx -f - <<EOF
apiVersion: batch/v1
kind: CronJob
metadata:
  name: awx-maintenance
spec:
  schedule: "0 3 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: maintenance
            image: quay.io/ansible/awx-ee:latest
            command: ["/bin/sh", "-c"]
            args:
              - |
                kubectl exec -n awx deployment/awx-demo-task -- awx-manage clearsessions
                kubectl exec -n awx deployment/awx-demo-task -- awx-manage clean_orphaned_workflow_nodes
                kubectl exec -n awx deployment/awx-demo-task -- awx-manage cleanup_jobs
          restartPolicy: OnFailure
EOF
8. System-Level Optimizations
On your Rocky Linux host:

bash
# Increase system limits
echo "fs.file-max = 2097152" | sudo tee -a /etc/sysctl.conf
echo "net.core.somaxconn = 65535" | sudo tee -a /etc/sysctl.conf
echo "vm.swappiness = 10" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Increase limits for k3s
echo "DefaultLimitNOFILE=65535" | sudo tee -a /etc/systemd/system/k3s.service.d/override.conf
echo "DefaultLimitNPROC=65535" | sudo tee -a /etc/systemd/system/k3s.service.d/override.conf
sudo systemctl daemon-reload
sudo systemctl restart k3s
9. Disaster Recovery Plan
Create a recovery script:

bash
cat <<'EOF' > awx-recovery.sh
#!/bin/bash
# Restore AWX from backup

# Restore PostgreSQL
kubectl exec -i -n awx awx-demo-postgres-0 -- psql -U awx -d awx < awx-postgres-backup.sql

# Restore AWX configuration
kubectl apply -f awx-resources.yaml
kubectl apply -f awx-secret.yaml
kubectl apply -f awx-tls-secret.yaml

# Restore AWX data
kubectl exec -i -n awx deployment/awx-demo-task -- awx-manage loaddata < awx-data.json

# Restart AWX
kubectl rollout restart deployment -n awx awx-demo-web
kubectl rollout restart deployment -n awx awx-demo-task
EOF
10. Documentation and Runbooks
Create operational documentation:

Standard Operating Procedures (SOPs):

AWX restart procedure

Backup verification process

Certificate renewal process

Troubleshooting Guide:

Common issues and resolutions

Escalation contacts

Maintenance Calendar:

Certificate expiration dates

Backup retention schedule

Implementation Notes
Apply these changes incrementally, testing at each step.

Monitor resource usage after each change.

Document all customizations for future reference.

Schedule regular reviews of the production setup (quarterly recommended).

These enhancements will provide a more robust, maintainable, and production-ready AWX deployment while maintaining your single-server architecture. The setup remains non-HA but gains significant improvements in reliability, security, and maintainability.


















how to check realtime resource utilization
To check real-time resource utilization of your AWX deployment on Kubernetes (k3s), you have several options:

1. Using kubectl top (Built-in)
bash
# For node resources
kubectl top node

# For pod resources
kubectl top pods -n awx

# For specific AWX components
kubectl top pod -n awx awx-prod-web-xxxxx
kubectl top pod -n awx awx-prod-task-xxxxx
kubectl top pod -n awx awx-prod-postgres-xxxxx
2. Container-level Metrics
bash
# Describe a pod to see resource limits and requests
kubectl describe pod -n awx awx-prod-web-xxxxx

# Get detailed metrics for a container
kubectl exec -n awx awx-prod-web-xxxxx -- cat /proc/1/status | grep -i rss
3. Kubernetes Dashboard
bash
# Install metrics-server (if not already installed)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Access dashboard (if installed)
kubectl proxy
# Then visit http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
4. Prometheus + Grafana (Recommended for Production)
bash
# Install kube-prometheus-stack
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring --create-namespace

# Port-forward Grafana
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
# Access http://localhost:3000 (admin/prom-operator)
5. AWX-specific Monitoring
bash
# Check AWX task memory usage
kubectl exec -n awx deployment/awx-prod-task -- free -h

# Check PostgreSQL memory usage
kubectl exec -n awx awx-prod-postgres-0 -- psql -U awx -c "SELECT * FROM pg_stat_activity;"
6. Host-level Monitoring
bash
# On the Rocky Linux host
sudo dnf install -y htop
htop

# Or use basic tools
watch -n 1 "free -h; echo; df -h; echo; uptime"
7. Custom Metrics Collection
bash
# Create a pod that continuously monitors resources
kubectl apply -n awx -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: resource-monitor
spec:
  containers:
  - name: monitor
    image: bitnami/shell
    command: ["/bin/sh", "-c"]
    args:
      - while true; do
          echo "=== $(date) ===";
          kubectl top pod -n awx;
          sleep 5;
        done
EOF

# View logs
kubectl logs -n awx resource-monitor -f
8. Persistent Monitoring Solution
For production, consider setting up:

Prometheus Alertmanager for alerts

Grafana dashboards with:

AWX job queue depth

PostgreSQL connection pool

Task container memory spikes

Loki for log aggregation

9. Quick Status Check Script
bash
#!/bin/bash
echo "=== Cluster Resources ==="
kubectl top node
echo -e "\n=== AWX Pods ==="
kubectl top pods -n awx
echo -e "\n=== Disk Usage ==="
kubectl exec -n awx awx-prod-postgres-0 -- df -h /var/lib/postgresql/data
echo -e "\n=== Task Container ==="
kubectl exec -n awx deployment/awx-prod-task -- free -h
For the most comprehensive monitoring, I recommend option #4 (Prometheus + Grafana) as it provides:

Historical data

Alerting capabilities

Custom dashboards

Correlation between metrics

Would you like me to elaborate on any particular monitoring approach?



















Here's the fastest way to completely stop and restart your AWX deployment on k3s without losing data (if you want a clean wipe instead, see the note at the end):

1. Stop All AWX Components
bash
# Scale down AWX and PostgreSQL
kubectl scale deployment -n awx --all --replicas=0

# Stop the AWX Operator
kubectl scale deployment -n awx awx-operator-controller-manager --replicas=0

# Verify everything is stopped
kubectl get pods -n awx  # Should show '0/0' for all deployments
2. Restart Everything
bash
# Restart the AWX Operator
kubectl scale deployment -n awx awx-operator-controller-manager --replicas=1

# Restart AWX and PostgreSQL
kubectl scale deployment -n awx --all --replicas=1

# Watch the pods come back up
watch kubectl get pods -n awx
3. Verify AWX is Healthy
bash
# Check pod statuses (wait for 'Running')
kubectl get pods -n awx

# Check AWX web service
kubectl get svc -n awx awx-prod-web
