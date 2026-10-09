# Running the pipeline on the Oracle VM

How to run TransitPulse's Dagster schedules (monthly BART + Bay Wheels ingest, model rebuilds, weekly forecast)
on the existing Oracle Cloud ARM VM, next to `seismicsocal.service`. Everything here is files in
[`deploy/oracle/`](../deploy/oracle/); nothing is deployed until you run the steps below.

| File | What it is |
|---|---|
| `bootstrap.sh` | Installs or updates everything (idempotent; re-run to update) |
| `transitpulse-dagster-daemon.service` | systemd unit: runs the schedules and the run queue |
| `transitpulse-dagster-web.service` | systemd unit: the Dagster UI on `127.0.0.1` only |
| `workspace.yaml` | Dagster code location (`pipeline.definitions`) |
| `transitpulse.env.example` | Environment for both units (no secrets) |

**Layout on the VM:** code in `/opt/transitpulse` (owned by the `transitpulse` system user, venv in `.venv`),
state in `/var/lib/transitpulse` (Dagster home, uv), config in `/etc/transitpulse` (env file + key file).
The UI listens on 127.0.0.1 only, so no firewall or security-list change is needed; you reach it over SSH.

## 1. Prerequisites

- The **existing** VM (no second VM is assumed or needed) with SSH access and `sudo`. Oracle Linux or Ubuntu;
  the script detects `dnf` or `apt`. ARM (`aarch64`) is expected; the script warns otherwise.
- **Size the VM first.** TransitPulse needs ~0.7 GB all the time (Dagster daemon + UI) plus **~5–6 GB during a
  Spark run** (4 GB driver + JVM overhead), a few minutes a month. Check headroom **with SeismicSoCal running**:
  ```sh
  free -h      # the "available" column must cover ~6 GB more than today's usage
  df -h /opt   # ~2 GB for code + venv, plus ~1 GB of working files under /opt/transitpulse/data
  nproc
  ```
  **Oracle Always Free limit (since 2026-06-15): 2 OCPUs and 12 GB of Ampere A1 memory per tenancy**, split across
  at most 2 instances (previously 4 / 24). Staying at or under 2 / 12 in total is $0 on both Free Tier and
  Pay-As-You-Go accounts; on Pay-As-You-Go, anything above it is billed.

  Measured on the SeismicSoCal VM (2026-10-08): **1 OCPU / 5.8 GiB, 3.2 GiB available, no swap** (SeismicSoCal
  ~0.8 GB, MLflow ~1.1 GB). A Spark run doesn't fit. **Resize the VM to 2 OCPUs / 12 GB** (still free): console →
  Compute → Instances → the VM → *More actions* → *Edit* → *Shape*. It reboots once; `seismicsocal.service` is
  enabled, so it starts again by itself. Afterwards ~9 GB is available.

  Optional safety net, recommended with no swap configured (a 4 GB swap file on the boot volume):
  ```sh
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```
- Defaults in the units and the env file assume the 2 OCPU / 12 GB VM: daemon `MemoryMax=7G`, Spark driver
  `TP_SPARK_DRIVER_MEMORY=4g`, `TP_ML_THREADS=2`, `DBT_THREADS=2`. Both units set `OOMScoreAdjust=500`, so if memory
  ever runs out the kernel kills TransitPulse, not SeismicSoCal. To change a limit, use a drop-in (it survives
  `bootstrap.sh` updates, which re-copy the unit files):
  ```sh
  sudo systemctl edit transitpulse-dagster-daemon     # add:  [Service]  MemoryMax=6G
  sudo systemctl restart transitpulse-dagster-daemon
  ```
  and lower `TP_SPARK_DRIVER_MEMORY` in `/etc/transitpulse/transitpulse.env` to match (keep it ~2 GB below
  `MemoryMax`).
- The GCP project, bucket and datasets already exist (Terraform in `infra/terraform`), and the `sa-pipeline`
  service account already has the roles it needs (`iam.tf`).

## 2. Create the `sa-pipeline` key (on your PC)

Save it inside your local clone under `credentials/`, which is gitignored (as is any `*-key.json`):

```sh
gcloud iam service-accounts keys create credentials/sa-pipeline-key.json \
  --iam-account=sa-pipeline@transitpulse-511002.iam.gserviceaccount.com
git check-ignore credentials/sa-pipeline-key.json   # prints the path = ignored; never commit it
```

## 3. Copy the key to the VM (scp)

```sh
scp credentials/sa-pipeline-key.json <user>@<vm>:/tmp/sa-pipeline-key.json
ssh <user>@<vm>
sudo install -d -m 755 /etc/transitpulse
sudo mv /tmp/sa-pipeline-key.json /etc/transitpulse/sa-pipeline-key.json
```

The `transitpulse` user is created by the bootstrap script, so set the owner after step 4's first run
(the script tells you), or create the user first with step 4 and then:

```sh
sudo chown transitpulse:transitpulse /etc/transitpulse/sa-pipeline-key.json
sudo chmod 600 /etc/transitpulse/sa-pipeline-key.json
```

The script refuses to start the services until the key is owned by `transitpulse` with mode `600`. It never prints
the key. Delete the local copy once the VM has it if you don't need it elsewhere.

## 4. Run the bootstrap

```sh
curl -fsSLO https://raw.githubusercontent.com/braaaeeedyn/transitpulse/main/deploy/oracle/bootstrap.sh
sudo bash bootstrap.sh
```

What it does, in order: installs `git`, `curl` and Java 17 (headless) from the distro; detects `JAVA_HOME`;
creates the `transitpulse` user and directories; installs `uv` for that user; clones (or fast-forwards)
the repo into `/opt/transitpulse`; `uv sync --frozen --group pipeline --group dbt --group ml --group spark`;
creates `/etc/transitpulse/transitpulse.env` from the example **only if it doesn't exist** (mode 600) with the
detected `JAVA_HOME`; copies `pipeline/dagster.yaml` into `DAGSTER_HOME`; runs `dbt parse` (dagster-dbt needs
`target/manifest.json`); checks the key; installs both units, `daemon-reload`, enables and (re)starts them.

Review `/etc/transitpulse/transitpulse.env` after the first run (`sudo nano /etc/transitpulse/transitpulse.env`),
then re-run the script.

## 5. Open the Dagster UI (SSH tunnel)

```sh
ssh -N -L 3000:127.0.0.1:3000 <user>@<vm>
```

Then open <http://localhost:3000>. (Change `TP_DAGSTER_PORT` in the env file if 3000 is taken on the VM.)

## 6. First backfill

In the UI: **Jobs → yearly_ingest → Partitions → Launch backfill** for 2018 → the current year. Runs carry the
`transitpulse/spark` tag and `pipeline/dagster.yaml` limits them to one at a time, so years run in sequence
(each Spark run uses a 4 GB driver). Then **baywheels_ingest** for the years you want (in-process DuckDB, no Spark),
then materialize the `warehouse` group (`dbt build` on BigQuery), then **weekly_forecast** once.
After that the schedules take over (Pacific time): BART on the 6th at 06:00, models at 08:00, Bay Wheels on the
7th at 06:30, forecast every Monday at 09:00. Turn schedules on in **Overview → Schedules**.

## 7. Verify

```sh
systemctl status transitpulse-dagster-daemon transitpulse-dagster-web
journalctl -u transitpulse-dagster-daemon -n 100 --no-pager
journalctl -u transitpulse-dagster-web -f
systemctl status seismicsocal       # still healthy?
free -h
```

In the UI, check the latest runs are green and the assets show fresh materializations.

## 8. Update

```sh
sudo bash /opt/transitpulse/deploy/oracle/bootstrap.sh
```

Pulls `main` (fast-forward only), re-syncs dependencies, re-parses dbt, re-installs the units and restarts them.
Your env file and key are left alone.

**After New Year**, restart the daemon once (`sudo systemctl restart transitpulse-dagster-daemon`, or run the
bootstrap). The yearly partitions are fixed when the code loads, so a daemon started in December doesn't offer the
new year for backfills. The January schedules don't need this: they load the previous month's year.

## 9. Uninstall

```sh
sudo systemctl disable --now transitpulse-dagster-daemon transitpulse-dagster-web
sudo rm /etc/systemd/system/transitpulse-dagster-{daemon,web}.service && sudo systemctl daemon-reload
sudo rm -rf /opt/transitpulse /var/lib/transitpulse
sudo rm -rf /etc/transitpulse        # removes the key file too
sudo userdel transitpulse
```

Also delete the service-account key in GCP if it isn't used elsewhere:
`gcloud iam service-accounts keys list --iam-account=sa-pipeline@transitpulse-511002.iam.gserviceaccount.com`.

## 10. Troubleshooting

- **Java version**: `java -version` must say 17 (Spark 3.5). If several JDKs are installed, set `JAVA_HOME` in the
  env file to the Java 17 one (`ls /usr/lib/jvm`) and restart the daemon.
- **Out of memory / runs killed**: `journalctl -u transitpulse-dagster-daemon | grep -i -E "oom|killed"`. Lower
  `TP_SPARK_DRIVER_MEMORY` in the env file, keep backfills sequential, or raise `MemoryMax=` with
  `sudo systemctl edit transitpulse-dagster-daemon` if the VM has room after SeismicSoCal (section 1).
- **ARM wheels**: every Python dependency in the `pipeline`, `dbt` and `ml` groups has an aarch64 wheel (checked in the
  repo with `uv pip compile ... --python-platform aarch64-manylinux_2_28 --only-binary :all:`). `pyspark` is pure
  Python (sdist). If `uv sync` tries to compile something, check `uname -m` and the uv output for the package.
- **Code location fails to load** (`manifest.json` not found): re-run the bootstrap, or
  `sudo -u transitpulse bash -c 'cd /opt/transitpulse && .venv/bin/dbt parse --project-dir dbt/transitpulse --profiles-dir dbt/transitpulse'`.
- **BigQuery permission errors**: the key must belong to `sa-pipeline`, and `GOOGLE_APPLICATION_CREDENTIALS` must
  point at it; `sudo -u transitpulse test -r /etc/transitpulse/sa-pipeline-key.json && echo readable`.
- **UI not reachable**: the web unit binds to 127.0.0.1 by design; use the SSH tunnel from step 5.
