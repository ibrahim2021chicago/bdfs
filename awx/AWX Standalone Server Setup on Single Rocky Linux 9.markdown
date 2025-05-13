# AWX Standalone Server Setup on Single Rocky Linux 9.5 Server with k3s

This guide provides detailed steps to install AWX v24.6.1 on a single Rocky Linux 9.5 server using the AWX Operator in a production environment with a self-signed certificate, deployed on a single-node k3s Kubernetes cluster. It replaces the problematic `kubeadm` setup, addressing issues with `containerd` CRI, CRI-O installation, and Kubernetes package errors. It includes persistent storage and steps to replace the self-signed certificate with a CA-issued certificate later. The setup is optimized for a standalone server without high availability (HA).

## Prerequisites

- **System Requirements**:
- 16 GB RAM
- 8 CPU cores
- At least 40 GB free disk space
- Rocky Linux 9.5 installed and updated (`sudo dnf update -y`)
- Single server

- **Software Requirements**:
- `curl`
- `git`
- `openssl`
- `kubectl` (optional, for interacting with k3s)

- **Network Requirements**:
- Static IP address (e.g., `192.168.1.10`)
- Fully qualified domain name (FQDN) for the server (e.g., `server.yourdomain.com`)
- FQDN for AWX (e.g., `awx.yourdomain.com`)
- Ports open:
   - k3s: 6443 (API server), 8472 (Flannel VXLAN)
   - AWX: 80 (HTTP), 443 (HTTPS)
- DNS or `/etc/hosts` configured to resolve server and AWX FQDNs

- **Production Considerations**:
- Single-node setup limits HA; ensure regular backups.
- Configure persistent storage for AWX’s PostgreSQL database.
- Use a secure AWX FQDN matching the future CA certificate.
- Monitor and log for reliability.

## Step-by-Step Installation

### Step 1: Prepare the Server

1. **Update the system**:
sudo dnf update -y
sudo reboot

2. **Disable swap** (required by k3s):
sudo swapoff -a
sudo sed -i '/ swap / s/^/#/' /etc/fstab

3. **Set hostname**:
sudo hostnamectl set-hostname server.yourdomain.com

4. **Configure /etc/hosts**:
sudo vi /etc/hosts
Add:
192.168.1.10 server.yourdomain.com
192.168.1.10 awx.yourdomain.com

Replace `192.168.1.10` with your server’s static IP.

5. **Verify hostname resolution**:
ping -c 3 server.yourdomain.com
ping -c 3 awx.yourdomain.com

6. **Configure firewall**:
sudo firewall-cmd --permanent --add-port=6443/tcp
sudo firewall-cmd --permanent --add-port=8472/udp
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

Verify:
sudo firewall-cmd --list-all

### Step 2: Install k3s

1. **Install k3s**:
curl -sfL https://get.k3s.io | sh -

This installs k3s with containerd as the default runtime, Traefik for ingress, and Flannel for networking.

2. **Verify k3s**:
sudo systemctl status k3s

3. **Configure kubectl**:
mkdir -p $HOME/.kube
sudo cp /etc/rancher/k3s/k3s.yaml $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
export KUBECONFIG=$HOME/.kube/config

4. **Verify cluster**:
kubectl get nodes

The node should be `Ready`.

### Step 3: Install Persistent Storage

1. **Install local-path-provisioner** (for AWX PostgreSQL):
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml

2. **Verify storage**:
kubectl get storageclass

You should see `local-path` as the default storage class.

### Step 4: Configure Traefik Ingress for AWX

K3s uses Traefik by default. We’ll configure it for AWX’s HTTPS access.

1. **Verify Traefik**:
kubectl get pods -n kube-system | grep traefik

2. **Set Traefik to use server’s IP**:
kubectl -n kube-system patch svc traefik -p '{"spec":{"externalIPs":["192.168.1.10"]}}'

Replace `192.168.1.10` with your server’s IP.

### Step 5: Install AWX Operator

1. **Create namespace**:
kubectl create namespace awx
kubectl config set-context --current --namespace=awx

2. **Clone AWX Operator repository**:
git clone https://github.com/ansible/awx-operator.git
cd awx-operator
git checkout tags/2.19.1

3. **Create kustomization.yaml**:
cat <<EOF > kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
   - github.com/ansible/awx-operator/config/default?ref=2.19.1
images:
   - name: quay.io/ansible/awx-operator
     newTag: 2.19.1
namespace: awx
EOF

4. **Apply kustomization**:
kubectl apply -k .

5. **Verify**:
kubectl get pods -n awx

### Step 6: Create AWX Instance with Self-Signed Certificate

1. **Generate self-signed certificate**:
openssl req -x509 -nodes -newkey rsa:4096 -keyout awx.key -out awx.crt -days 365 -subj "/CN=awx.yourdomain.com" -addext "subjectAltName=DNS:awx.yourdomain.com"

2. **Create secret**:
kubectl create secret tls awx-tls-secret --cert=awx.crt --key=awx.key -n awx

3. **Create awx-prod.yaml**:
cat <<EOF > awx-prod.yaml
apiVersion: awx.ansible.com/v1beta1
kind: AWX
metadata:
   name: awx-prod
spec:
   service_type: ClusterIP
   hostname: awx.yourdomain.com
   ingress_type: ingress
   ingress_tls_secret: awx-tls-secret
   ingress_annotations:
      kubernetes.io/ingress.class: traefik
      traefik.ingress.kubernetes.io/router.tls: "true"
   postgres_storage_class: local-path
   postgres_storage_requirements:
      requests:
      storage: 10Gi
EOF

Replace `awx.yourdomain.com` with your AWX FQDN.

4. **Apply AWX instance**:
kubectl apply -f awx-prod.yaml

5. **Monitor deployment**:
kubectl get pods -n awx

Wait until `awx-prod` pods are `Running` (5-10 minutes).

### Step 7: Access AWX

1. **Retrieve admin password**:
kubectl get secret awx-prod-admin-password -o jsonpath="{.data.password}" -n awx | base64 --decode ; echo

2. **Access AWX**: Navigate to `https://awx.yourdomain.com`. Accept the self-signed certificate warning.
- **Username**: `admin`
- **Password**: From step 1.

### Step 8: Production Considerations

- **Backups**:

  ```bash
  kubectl get secret awx-prod-admin-password -n awx -o yaml > awx-secret-backup.yaml
  ```

  Backup `/var/lib/rancher/k3s/storage` (k3s SQLite and local-path data).

- **Monitoring**:

  ```bash
  kubectl get pods -n awx -w
  ```

- **Logging**:

  ```bash
  kubectl logs -n awx <awx-prod-pod-name>
  ```

- **Single-Node Risks**:

  Monitor disk space:

  ```bash
  df -h
  ```

- **K3s Upgrades**:

  ```bash
  curl -sfL https://get.k3s.io | sh -
  ```

### Step 9: Replacing Self-Signed Certificate

1. **Obtain CA certificate**:

   - `awx-ca.crt`
   - `awx-ca.key`

2. **Update secret**:

   ```bash
   kubectl create secret tls awx-tls-secret --cert=awx-ca.crt --key=awx-ca.key -n awx --dry-run=client -o yaml | kubectl apply -f -
   ```

3. **Restart AWX pods**:

   ```bash
   kubectl delete pod -n awx -l app.kubernetes.io/name=awx-prod

4. **Verify**: Access `https://awx.yourdomain.com`.

## Troubleshooting

- **K3s Installation**:

  ```bash
  sudo journalctl -u k3s
  ```

- **AWX Pods Not Running**:

  ```bash
  kubectl describe pod -n awx <awx-prod-pod-name>
  ```

- **Traefik Issues**:

  ```bash
  kubectl logs -n kube-system -l app=traefik
  ```

- **Storage Issues**:

  ```bash
  kubectl describe pvc -n awx
  ```

- **Network Issues**:

  Verify Traefik service:

  ```bash
  kubectl get svc -n kube-system traefik
  ```

## Notes

- Check AWX Operator updates: https://github.com/ansible/awx-operator/releases
- For critical data, consider external PostgreSQL.
- For advanced storage, evaluate NFS or Longhorn instead of `local-path-provisioner`.
- K3s documentation: https://docs.k3s.io