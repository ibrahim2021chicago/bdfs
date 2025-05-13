Changing Local Path Provisioner Storage Location from /opt to /var/lib
To modify the storage location from /opt/local-path-provisioner to /var/lib/rancher/k3s/storage, follow these steps:

1. Update the Local Path Provisioner ConfigMap
bash
kubectl edit configmap local-path-config -n local-path-storage
Replace the content with:

yaml
data:
  config.json: |-
    {
      "nodePathMap":[
        {
          "node":"DEFAULT_PATH_FOR_NON_LISTED_NODES",
          "paths":["/var/lib/rancher/k3s/storage"]
        }
      ]
    }
2. Restart the Local Path Provisioner
bash
kubectl rollout restart deployment local-path-provisioner -n local-path-storage
3. Verify the Changes
bash
kubectl get pods -n local-path-storage
kubectl logs -n local-path-storage -l app=local-path-provisioner
4. Clean Up Existing Persistent Volumes (If Needed)
For new PVCs to use the new location, you may need to:

bash
# Delete existing PVCs (will delete your data!)
kubectl delete pvc --all -n awx

# Delete the PVs
kubectl delete pv --all
5. Create Directory and Set Permissions
On each node:

bash
sudo mkdir -p /var/lib/rancher/k3s/storage
sudo chmod -R 777 /var/lib/rancher/k3s/storage
sudo chown -R k3s:k3s /var/lib/rancher/k3s/storage
6. Redeploy AWX
bash
kubectl apply -f awx-prod.yaml