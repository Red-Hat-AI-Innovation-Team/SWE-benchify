Container shows "Health": {"Status": "starting"} even though no healthcheck is defined
### Issue Description

The container is running normally, but **podman ps** still reports its status as starting. There’s no health check configured.

```
# podman ps
CONTAINER ID  IMAGE       COMMAND     CREATED         STATUS                    PORTS       NAMES
c4c0e5372bef              /sbin/init  47 minutes ago  Up 47 minutes (starting)              qm

# podman inspect qm --format '{{json .Config.Healthcheck}}'
{}

# podman inspect qm --format '{{.State.Status}}'
running

# podman inspect qm --format '{{json .State.Health}}'
{"Status":"starting","FailingStreak":0,"Log":null}

# rpm -qa | grep -i podman
python3-podman-5.6.0-1.el10.noarch
podman-5.6.0-6.el10_1.x86_64
cockpit-podman-116-1.el10.noarch
podman-docker-5.6.0-6.el10_1.noarch

# rpm -qa | grep -i qm
qm-1.0-1.el10iv.noarch
```

### Steps to reproduce the issue

I was able to reproduce the issue using CS10 image with podman 5.6.0-1


### Describe the results you received

```
# podman ps
CONTAINER ID  IMAGE       COMMAND     CREATED         STATUS                    PORTS       NAMES
c4c0e5372bef              /sbin/init  47 minutes ago  Up 47 minutes (starting)              qm
```


### Describe the results you expected

podman ps do not show starting as the container is running by hour or so.

### podman info output

```yaml
host:
  arch: amd64
  buildahVersion: 1.41.5
  cgroupControllers:
  - cpuset
  - cpu
  - io
  - memory
  - pids
  - rdma
  - misc
  - dmem
  cgroupManager: systemd
  cgroupVersion: v2
  conmon:
    package: conmon-2.1.13-1.el10.x86_64
    path: /usr/bin/conmon
    version: 'conmon version 2.1.13, commit: '
  cpuUtilization:
    idlePercent: 99.65
    systemPercent: 0.23
    userPercent: 0.12
  cpus: 8
  databaseBackend: sqlite
  distribution:
    distribution: rhivos
    version: "2.0"
  eventLogger: journald
  freeLocks: 2047
  hostname: localhost
  idMappings:
    gidmap: null
    uidmap: null
  kernel: 6.12.0-126.el10iv.x86_64
  linkmode: dynamic
  logDriver: journald
  memFree: 1535217664
  memTotal: 2056601600
  networkBackend: netavark
  networkBackendInfo:
    backend: netavark
    dns:
      package: aardvark-dns-1.16.0-2.el10.x86_64
      path: /usr/libexec/podman/aardvark-dns
      version: aardvark-dns 1.16.0
    package: netavark-1.16.0-1.el10.x86_64
    path: /usr/libexec/podman/netavark
    version: netavark 1.16.0
  ociRuntime:
    name: crun
    package: crun-1.24-1.el10.x86_64
    path: /usr/bin/crun
    version: |-
      crun version 1.24
      commit: 54693209039e5e04cbe3c8b1cd5fe2301219f0a1
      rundir: /run/user/0/crun
      spec: 1.0.0
      +SYSTEMD +SELINUX +APPARMOR +CAP +SECCOMP +EBPF +CRIU +YAJL
  os: linux
  pasta:
    executable: /usr/bin/pasta
    package: passt-0^20250512.g8ec1341-4.el10_1.x86_64
    version: ""
  remoteSocket:
    exists: true
    path: /run/podman/podman.sock
  rootlessNetworkCmd: pasta
  security:
    apparmorEnabled: false
    capabilities: CAP_CHOWN,CAP_DAC_OVERRIDE,CAP_FOWNER,CAP_FSETID,CAP_KILL,CAP_NET_BIND_SERVICE,CAP_SETFCAP,CAP_SETGID,CAP_SETPCAP,CAP_SETUID,CAP_SYS_CHROOT
    rootless: false
    seccompEnabled: true
    seccompProfilePath: /usr/share/containers/seccomp.json
    selinuxEnabled: true
  serviceIsRemote: false
  slirp4netns:
    executable: /usr/bin/slirp4netns
    package: slirp4netns-1.3.3-1.el10.x86_64
    version: |-
      slirp4netns version 1.3.3
      commit: 944fa94090e1fd1312232cbc0e6b43585553d824
      libslirp: 4.7.0
      SLIRP_CONFIG_VERSION_MAX: 4
      libseccomp: 2.5.6
  swapFree: 0
  swapTotal: 0
  uptime: 0h 26m 17.00s
  variant: ""
plugins:
  authorization: null
  log:
  - k8s-file
  - none
  - passthrough
  - journald
  network:
  - bridge
  - macvlan
  - ipvlan
  volume:
  - local
registries:
  search:
  - registry.access.redhat.com
  - registry.redhat.io
  - docker.io
store:
  configFile: /usr/share/containers/storage.conf
  containerStore:
    number: 1
    paused: 0
    running: 1
    stopped: 0
  graphDriverName: overlay
  graphOptions:
    overlay.mountopt: nodev,metacopy=on
  graphRoot: /var/lib/containers/storage
  graphRootAllocated: 9036328960
  graphRootUsed: 7858274304
  graphStatus:
    Backing Filesystem: extfs
    Native Overlay Diff: "false"
    Supports d_type: "true"
    Supports shifting: "true"
    Supports volatile: "true"
    Using metacopy: "true"
  imageCopyTmpDir: /var/tmp
  imageStore:
    number: 0
  runRoot: /run/containers/storage
  transientStore: true
  volumePath: /var/lib/containers/storage/volumes
version:
  APIVersion: 5.6.0
  BuildOrigin: Red Hat, Inc. <http://bugzilla.redhat.com/bugzilla>
  Built: 1762732800
  BuiltTime: Mon Nov 10 00:00:00 2025
  GitCommit: 279100774abf1292cf4f14769abd6b360a678656
  GoVersion: go1.24.6 (Red Hat 1.24.6-1.el10)
  Os: linux
  OsArch: linux/amd64
  Version: 5.6.0
```

### Podman in a container

No

### Privileged Or Rootless

None

### Upstream Latest Release

No

### Additional environment details

podman inspect qm
```
[
     {
          "Id": "c4c0e5372bef04eb5744302141d9cea539d291fcc3392ed495f779ca862494bc",
          "Created": "2025-12-01T14:50:49.36282613Z",
          "Path": "/sbin/init",
          "Args": [
               "/sbin/init"
          ],
          "State": {
               "OciVersion": "1.2.1",
               "Status": "running",
               "Running": true,
               "Paused": false,
               "Restarting": false,
               "OOMKilled": false,
               "Dead": false,
               "Pid": 972,
               "ConmonPid": 955,
               "ExitCode": 0,
               "Error": "",
               "StartedAt": "2025-12-01T14:50:50.598661698Z",
               "FinishedAt": "0001-01-01T00:00:00Z",
               "Health": {
                    "Status": "starting",
                    "FailingStreak": 0,
                    "Log": null
               },
               "CgroupPath": "/qm.service/libpod-payload-c4c0e5372bef04eb5744302141d9cea539d291fcc3392ed495f779ca862494bc",
               "CheckpointedAt": "0001-01-01T00:00:00Z",
               "RestoredAt": "0001-01-01T00:00:00Z"
          },
          "Image": "",
          "ImageDigest": "",
          "ImageName": "",
          "Rootfs": "/usr/lib/qm/rootfs",
          "Pod": "",
          "ResolvConfPath": "/run/containers/storage/overlay-containers/c4c0e5372bef04eb5744302141d9cea539d291fcc3392ed495f779ca862494bc/userdata/resolv.conf",
          "HostnamePath": "/run/containers/storage/overlay-containers/c4c0e5372bef04eb5744302141d9cea539d291fcc3392ed495f779ca862494bc/userdata/hostname",
          "HostsPath": "/run/containers/storage/overlay-containers/c4c0e5372bef04eb5744302141d9cea539d291fcc3392ed495f779ca862494bc/userdata/hosts",
          "StaticDir": "/var/lib/containers/storage/overlay-containers/c4c0e5372bef04eb5744302141d9cea539d291fcc3392ed495f779ca862494bc/userdata",
          "OCIConfigPath": "/run/containers/storage/overlay-containers/c4c0e5372bef04eb5744302141d9cea539d291fcc3392ed495f779ca862494bc/userdata/config.json",
          "OCIRuntime": "crun",
          "ConmonPidFile": "/run/containers/storage/overlay-containers/c4c0e5372bef04eb5744302141d9cea539d291fcc3392ed495f779ca862494bc/userdata/conmon.pid",
          "PidFile": "/run/containers/storage/overlay-containers/c4c0e5372bef04eb5744302141d9cea539d291fcc3392ed495f779ca862494bc/userdata/pidfile",
          "Name": "qm",
          "RestartCount": 0,
          "Driver": "overlay",
          "MountLabel": "system_u:object_r:qm_file_t:s0",
          "ProcessLabel": "system_u:system_r:qm_t:s0",
          "AppArmorProfile": "",
          "EffectiveCaps": [
               "CAP_AUDIT_CONTROL",
               "CAP_AUDIT_READ",
               "CAP_AUDIT_WRITE",
               "CAP_BLOCK_SUSPEND",
               "CAP_BPF",
               "CAP_CHECKPOINT_RESTORE",
               "CAP_CHOWN",
               "CAP_DAC_OVERRIDE",
               "CAP_DAC_READ_SEARCH",
               "CAP_FOWNER",
               "CAP_FSETID",
               "CAP_IPC_LOCK",
               "CAP_IPC_OWNER",
               "CAP_KILL",
               "CAP_LEASE",
               "CAP_LINUX_IMMUTABLE",
               "CAP_MAC_ADMIN",
               "CAP_MAC_OVERRIDE",
               "CAP_MKNOD",
               "CAP_NET_ADMIN",
               "CAP_NET_BIND_SERVICE",
               "CAP_NET_BROADCAST",
               "CAP_NET_RAW",
               "CAP_PERFMON",
               "CAP_SETFCAP",
               "CAP_SETGID",
               "CAP_SETPCAP",
               "CAP_SETUID",
               "CAP_SYSLOG",
               "CAP_SYS_ADMIN",
               "CAP_SYS_CHROOT",
               "CAP_SYS_MODULE",
               "CAP_SYS_NICE",
               "CAP_SYS_PACCT",
               "CAP_SYS_PTRACE",
               "CAP_SYS_RAWIO",
               "CAP_SYS_TIME",
               "CAP_SYS_TTY_CONFIG",
               "CAP_WAKE_ALARM"
          ],
          "BoundingCaps": [
               "CAP_AUDIT_CONTROL",
               "CAP_AUDIT_READ",
               "CAP_AUDIT_WRITE",
               "CAP_BLOCK_SUSPEND",
               "CAP_BPF",
               "CAP_CHECKPOINT_RESTORE",
               "CAP_CHOWN",
               "CAP_DAC_OVERRIDE",
               "CAP_DAC_READ_SEARCH",
               "CAP_FOWNER",
               "CAP_FSETID",
               "CAP_IPC_LOCK",
               "CAP_IPC_OWNER",
               "CAP_KILL",
               "CAP_LEASE",
               "CAP_LINUX_IMMUTABLE",
               "CAP_MAC_ADMIN",
               "CAP_MAC_OVERRIDE",
               "CAP_MKNOD",
               "CAP_NET_ADMIN",
               "CAP_NET_BIND_SERVICE",
               "CAP_NET_BROADCAST",
               "CAP_NET_RAW",
               "CAP_PERFMON",
               "CAP_SETFCAP",
               "CAP_SETGID",
               "CAP_SETPCAP",
               "CAP_SETUID",
               "CAP_SYSLOG",
               "CAP_SYS_ADMIN",
               "CAP_SYS_CHROOT",
               "CAP_SYS_MODULE",
               "CAP_SYS_NICE",
               "CAP_SYS_PACCT",
               "CAP_SYS_PTRACE",
               "CAP_SYS_RAWIO",
               "CAP_SYS_TIME",
               "CAP_SYS_TTY_CONFIG",
               "CAP_WAKE_ALARM"
          ],
          "ExecIDs": [],
          "GraphDriver": {
               "Name": "overlay",
               "Data": {
                    "UpperDir": "/var/lib/containers/storage/overlay/5855aba25605d0da59ea41acd9d80579bb50e4fe17c0713ff926d09351a82a79/diff",
                    "WorkDir": "/var/lib/containers/storage/overlay/5855aba25605d0da59ea41acd9d80579bb50e4fe17c0713ff926d09351a82a79/work"
               }
          },
          "Mounts": [
               {
                    "Type": "bind",
                    "Source": "/etc/qm",
                    "Destination": "/etc",
                    "Driver": "",
                    "Mode": "",
                    "Options": [
                         "rbind"
                    ],
                    "RW": true,
                    "Propagation": "rprivate"
               },
               {
                    "Type": "bind",
                    "Source": "/var/qm",
                    "Destination": "/var",
                    "Driver": "",
                    "Mode": "",
                    "Options": [
                         "rbind"
                    ],
                    "RW": true,
                    "Propagation": "rprivate"
               },
               {
                    "Type": "bind",
                    "Source": "/var/qm/tmp",
                    "Destination": "/var/tmp",
                    "Driver": "",
                    "Mode": "",
                    "Options": [
                         "rbind"
                    ],
                    "RW": true,
                    "Propagation": "rprivate"
               },
               {
                    "Type": "bind",
                    "Source": "/sys/fs/selinux",
                    "Destination": "/sys/fs/selinux",
                    "Driver": "",
                    "Mode": "",
                    "Options": [
                         "noexec",
                         "nosuid",
                         "rbind"
                    ],
                    "RW": true,
                    "Propagation": "rprivate"
               }
          ],
          "Dependencies": [],
          "NetworkSettings": {
               "EndpointID": "",
               "Gateway": "10.88.0.1",
               "IPAddress": "10.88.0.2",
               "IPPrefixLen": 16,
               "IPv6Gateway": "",
               "GlobalIPv6Address": "",
               "GlobalIPv6PrefixLen": 0,
               "MacAddress": "e6:74:25:20:bf:cf",
               "Bridge": "",
               "SandboxID": "",
               "HairpinMode": false,
               "LinkLocalIPv6Address": "",
               "LinkLocalIPv6PrefixLen": 0,
               "Ports": {},
               "SandboxKey": "/run/netns/netns-b7a8e008-a0ef-14c0-e112-678b2a6c3321",
               "Networks": {
                    "podman": {
                         "EndpointID": "",
                         "Gateway": "10.88.0.1",
                         "IPAddress": "10.88.0.2",
                         "IPPrefixLen": 16,
                         "IPv6Gateway": "",
                         "GlobalIPv6Address": "",
                         "GlobalIPv6PrefixLen": 0,
                         "MacAddress": "e6:74:25:20:bf:cf",
                         "NetworkID": "2f259bab93aaaaa2542ba43ef33eb990d0999ee1b9924b557b7be53c0b7a1bb9",
                         "DriverOpts": null,
                         "IPAMConfig": null,
                         "Links": null,
                         "Aliases": [
                              "c4c0e5372bef"
                         ]
                    }
               }
          },
          "Namespace": "",
          "IsInfra": false,
          "IsService": false,
          "KubeExitCodePropagation": "invalid",
          "lockNumber": 0,
          "Config": {
               "Hostname": "c4c0e5372bef",
               "Domainname": "",
               "User": "",
               "AttachStdin": false,
               "AttachStdout": false,
               "AttachStderr": false,
               "Tty": false,
               "OpenStdin": false,
               "StdinOnce": false,
               "Env": [
                    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                    "HOME=/root",
                    "container_uuid=c4c0e5372bef04eb5744302141d9cea5",
                    "HOSTNAME=c4c0e5372bef"
               ],
               "Cmd": [
                    "/sbin/init"
               ],
               "Image": "",
               "Volumes": null,
               "WorkingDir": "/",
               "Entrypoint": null,
               "OnBuild": null,
               "Labels": {
                    "PODMAN_SYSTEMD_UNIT": "qm.service"
               },
               "Annotations": {
                    "io.container.manager": "libpod",
                    "io.podman.annotations.autoremove": "TRUE",
                    "io.podman.annotations.label": "type:qm_t,label=filetype:qm_file_t,label=level:s0",
                    "io.podman.annotations.pids-limit": "-1",
                    "io.podman.annotations.seccomp": "/usr/share/qm/seccomp-no-rt.json",
                    "org.opencontainers.image.stopSignal": "37",
                    "org.systemd.property.KillSignal": "37",
                    "org.systemd.property.TimeoutStopUSec": "uint64 10000000",
                    "run.oci.mount_context_type": "rootcontext"
               },
               "StopSignal": "SIGRTMIN+3",
               "Healthcheck": {},
               "HealthcheckOnFailureAction": "none",
               "HealthLogDestination": "local",
               "HealthcheckMaxLogCount": 5,
               "HealthcheckMaxLogSize": 500,
               "CreateCommand": [
                    "/usr/bin/podman",
                    "run",
                    "--name",
                    "qm",
                    "--replace",
                    "--rm",
                    "--cgroups=split",
                    "--pids-limit",
                    "-1",
                    "--read-only-tmpfs",
                    "--network",
                    "private",
                    "--sdnotify=conmon",
                    "-d",
                    "--security-opt",
                    "label=nested",
                    "--security-opt",
                    "label=type:qm_t",
                    "--security-opt",
                    "label=filetype:qm_file_t",
                    "--security-opt",
                    "label=level:s0",
                    "--security-opt",
                    "seccomp=/usr/share/qm/seccomp-no-rt.json",
                    "--cap-drop",
                    "sys_boot",
                    "--cap-drop",
                    "sys_resource",
                    "--cap-add",
                    "all",
                    "--sysctl",
                    "fs.mqueue.queues_max=4",
                    "--read-only",
                    "-v",
                    "/etc/qm:/etc",
                    "-v",
                    "/var/qm:/var",
                    "-v",
                    "/var/qm/tmp:/var/tmp",
                    "--env",
                    "TZ",
                    "--rootfs",
                    "/usr/lib/qm/rootfs",
                    "/sbin/init"
               ],
               "SystemdMode": true,
               "Umask": "0022",
               "Timeout": 0,
               "StopTimeout": 10,
               "Passwd": true,
               "sdNotifyMode": "conmon",
               "sdNotifySocket": "/run/systemd/notify"
          },
          "HostConfig": {
               "Binds": [
                    "/etc/qm:/etc:rprivate,rbind",
                    "/var/qm:/var:rprivate,rbind",
                    "/var/qm/tmp:/var/tmp:rprivate,rbind",
                    "/sys/fs/selinux:/sys/fs/selinux:rprivate,noexec,nosuid,rbind"
               ],
               "CgroupManager": "systemd",
               "CgroupMode": "private",
               "ContainerIDFile": "",
               "LogConfig": {
                    "Type": "journald",
                    "Config": null,
                    "Path": "",
                    "Tag": "",
                    "Size": "-1B"
               },
               "NetworkMode": "bridge",
               "PortBindings": {},
               "RestartPolicy": {
                    "Name": "no",
                    "MaximumRetryCount": 0
               },
               "AutoRemove": true,
               "AutoRemoveImage": false,
               "Annotations": {
                    "io.container.manager": "libpod",
                    "io.podman.annotations.autoremove": "TRUE",
                    "io.podman.annotations.label": "type:qm_t,label=filetype:qm_file_t,label=level:s0",
                    "io.podman.annotations.pids-limit": "-1",
                    "io.podman.annotations.seccomp": "/usr/share/qm/seccomp-no-rt.json",
                    "org.opencontainers.image.stopSignal": "37",
                    "org.systemd.property.KillSignal": "37",
                    "org.systemd.property.TimeoutStopUSec": "uint64 10000000",
                    "run.oci.mount_context_type": "rootcontext"
               },
               "VolumeDriver": "",
               "VolumesFrom": null,
               "CapAdd": [
                    "CAP_AUDIT_CONTROL",
                    "CAP_AUDIT_READ",
                    "CAP_AUDIT_WRITE",
                    "CAP_BLOCK_SUSPEND",
                    "CAP_BPF",
                    "CAP_CHECKPOINT_RESTORE",
                    "CAP_DAC_READ_SEARCH",
                    "CAP_IPC_LOCK",
                    "CAP_IPC_OWNER",
                    "CAP_LEASE",
                    "CAP_LINUX_IMMUTABLE",
                    "CAP_MAC_ADMIN",
                    "CAP_MAC_OVERRIDE",
                    "CAP_MKNOD",
                    "CAP_NET_ADMIN",
                    "CAP_NET_BROADCAST",
                    "CAP_NET_RAW",
                    "CAP_PERFMON",
                    "CAP_SYSLOG",
                    "CAP_SYS_ADMIN",
                    "CAP_SYS_MODULE",
                    "CAP_SYS_NICE",
                    "CAP_SYS_PACCT",
                    "CAP_SYS_PTRACE",
                    "CAP_SYS_RAWIO",
                    "CAP_SYS_TIME",
                    "CAP_SYS_TTY_CONFIG",
                    "CAP_WAKE_ALARM"
               ],
               "CapDrop": [],
               "Dns": [],
               "DnsOptions": [],
               "DnsSearch": [],
               "ExtraHosts": [],
               "HostsFile": "",
               "GroupAdd": [],
               "IpcMode": "shareable",
               "Cgroup": "",
               "Cgroups": "default",
               "Links": null,
               "OomScoreAdj": 0,
               "PidMode": "private",
               "Privileged": false,
               "PublishAllPorts": false,
               "ReadonlyRootfs": true,
               "SecurityOpt": [
                    "label=type:qm_t,label=filetype:qm_file_t,label=level:s0",
                    "seccomp=/usr/share/qm/seccomp-no-rt.json"
               ],
               "Tmpfs": {},
               "UTSMode": "private",
               "UsernsMode": "",
               "ShmSize": 65536000,
               "Runtime": "oci",
               "ConsoleSize": [
                    0,
                    0
               ],
               "Isolation": "",
               "CpuShares": 0,
               "Memory": 0,
               "NanoCpus": 0,
               "CgroupParent": "",
               "BlkioWeight": 0,
               "BlkioWeightDevice": null,
               "BlkioDeviceReadBps": null,
               "BlkioDeviceWriteBps": null,
               "BlkioDeviceReadIOps": null,
               "BlkioDeviceWriteIOps": null,
               "CpuPeriod": 0,
               "CpuQuota": 0,
               "CpuRealtimePeriod": 0,
               "CpuRealtimeRuntime": 0,
               "CpusetCpus": "",
               "CpusetMems": "",
               "Devices": [],
               "DiskQuota": 0,
               "KernelMemory": 0,
               "MemoryReservation": 0,
               "MemorySwap": 0,
               "MemorySwappiness": 0,
               "OomKillDisable": false,
               "PidsLimit": -1,
               "Ulimits": [
                    {
                         "Name": "RLIMIT_NOFILE",
                         "Soft": 1048576,
                         "Hard": 1048576
                    },
                    {
                         "Name": "RLIMIT_NPROC",
                         "Soft": 1048576,
                         "Hard": 1048576
                    }
               ],
               "CpuCount": 0,
               "CpuPercent": 0,
               "IOMaximumIOps": 0,
               "IOMaximumBandwidth": 0,
               "CgroupConf": null
          },
          "UseImageHosts": false,
          "UseImageHostname": false
     }
]
```
### Additional information

Additional information like issue happens only occasionally or issue happens with a particular architecture or on a particular setting

**Repository:** `containers/podman`
**Base commit:** `a51012b99e64f4f5a4efd4e438b7485f156cfffe`

## Hints

I originally found this on my mac, but @dougsland found it on x86 as well.

Do we need to specify something else in QM?

Hello, I'm interested in contributing and would like to work on this issue if it's available.

My classmate [Ian Kim](https://github.com/iankmm) and I are CS students at the University of Texas, currently taking a virtualization course that includes an open-source contribution component.

We proposed this issue to our professor, and he approved it as a suitable contribution. Could this be assigned to me?

Thanks!

@mheon 
Doew this rings a bell? it is c10s
some more details in QM repo issue
https://github.com/containers/qm/issues/947#issuecomment-3574402361


Yeah, we're familiar with this one. I'm pretty sure the core problem here is https://github.com/containers/podman/blob/main/libpod/container_inspect.go#L198 - note the `!= 1` check, which should match 0 - meaning a defined, but empty, healthcheck. I suspect changing that to `> 1` would fix at least the inspect bit, though `podman ps` apparently has issues as well?

@jasonoh11 If you want it, it's yours, you can self-assign with the `/assign` command.

Thanks, that makes sense, we're going to start by trying to reproduce the issue through a unit test and then look into the `podman ps` issue as well

/assign

Of note: this only reproduces when using `--rootfs`, not when creating from an image. Not 100% sure why, probably has something to do with the defaults we use for healthchecks in that case?
