# SP1 Cluster Deployment Guide for Single GCP VM with Multiple GPUs

This guide details the configuration changes and setup required to deploy a self-hosted `sp1-cluster` on a single GCP VM with multiple GPUs for accelerated zero-knowledge proof generation.

### Step 1: Clone the Repository
SSH into your GCP VM and run:
```bash
git clone https://github.com/succinctlabs/sp1-cluster.git
cd sp1-cluster
```

### Step 2: Increase the timeouts
sp1-cluster has hardcoded timeouts at multiple places that we need to override in order to execute long running proof generation jobs. Specifically, we need to increase the timeouts for the following:
- bin/cli/src/commands/vk_gen.rs: `VK_GEN_TIMEOUT`
- bin/node/src/main.rs: `TASK_TIMEOUT`
- crates/artifact/src/redis.rs: `ARTIFACT_TIMEOUT_SECONDS`


### Step 3: Update the docker files to build the modified binaries
In the sp1-cluster architecture:
- coordinator: Manages the cluster state, queues tasks, and dispatches work.
- node (or worker): Actually executes the SP1 proof generation on your hardware (CPU/GPU).
- bidder and fulfiller: These components are used to interact with the public Succinct Prover Network (e.g., bidding on proof requests from the network or fulfilling them).

For a self-hosted, private cluster, we can safely remove the bidder and fulfiller services from the docker-compose.yml. We will also remove resource limits on cpu and memory usage and update the `image:` field to use locally built images. 

The infra/docker-compose.yml file should look like this:
```yml
services:
  # Redis service
  redis:
    image: bitnamisecure/redis:latest
    environment:
      - REDIS_PASSWORD=redispassword
      - REDIS_AOF_ENABLED=no
    volumes:
      - redis_data:/bitnami/redis/data
    ports:
      - "127.0.0.1:6379:6379"
    restart: always

  # PostgreSQL database
  postgresql:
    image: bitnamisecure/postgresql:latest
    environment:
      - POSTGRES_PASSWORD=postgrespassword
      - POSTGRES_USER=postgres
      - POSTGRES_DB=postgres
    volumes:
      - postgresql_data:/bitnami/postgresql
    ports:
      - "5432:5432"

  # API Service
  api:
    image: sp1-cluster-local:base
    environment:
      - API_GRPC_ADDR=0.0.0.0:50051
      - API_HTTP_ADDR=0.0.0.0:3000
      - API_AUTO_MIGRATE=true
      - API_DATABASE_URL=postgresql://postgres:postgrespassword@postgresql:5432/postgres
    ports:
      - "127.0.0.1:50051:50051"
    depends_on:
      - postgresql

  # Coordinator Service
  coordinator:
    image: sp1-cluster-local:base
    environment:
      - COORDINATOR_CLUSTER_RPC=http://api:50051
      - COORDINATOR_METRICS_ADDR=0.0.0.0:9090
      - COORDINATOR_ADDR=0.0.0.0:50051
    command: ["/bin/sh", "-c", "/coordinator"]
    # Expose coordinator for remote workers connecting from other machines.
    ports:
      - "0.0.0.0:50053:50051"
    depends_on:
      - api

  # CPU Node
  cpu-node:
    image: sp1-cluster-local:base
    environment:
      - NODE_COORDINATOR_RPC=http://coordinator:50051
      - WORKER_MAX_WEIGHT_OVERRIDE=48
      - WORKER_CONTROLLER_WEIGHT=16
      - NODE_ARTIFACT_STORE=redis
      - NODE_REDIS_NODES=redis://:redispassword@redis:6379/0
      - WORKER_TYPE=CPU
    volumes:
      - ${HOME}/.sp1/circuits:/root/.sp1/circuits
    command: ["/bin/sh", "-c", "/node"]
    restart: always
    depends_on:
      - coordinator
      - redis

  # CPU Node
  mixed:
    image: sp1-cluster-local:base
    environment:
      - NODE_COORDINATOR_RPC=http://coordinator:50051
      - WORKER_MAX_WEIGHT_OVERRIDE=48
      - WORKER_CONTROLLER_WEIGHT=16
      - NODE_ARTIFACT_STORE=redis
      - NODE_REDIS_NODES=redis://:redispassword@redis:6379/0
      - WORKER_TYPE=ALL
    volumes:
      - ${HOME}/.sp1/circuits:/root/.sp1/circuits
    command: ["/bin/sh", "-c", "/app/sp1-cluster-node"]
    restart: always
    depends_on:
      - coordinator
      - redis

  # GPU Node
  gpu0:
    image: sp1-cluster-local:node-gpu
    environment:
      - NODE_COORDINATOR_RPC=http://coordinator:50051
      - WORKER_MAX_WEIGHT_OVERRIDE=24
      - NODE_ARTIFACT_STORE=redis
      - NODE_REDIS_NODES=redis://:redispassword@redis:6379/0
      - WORKER_TYPE=GPU
    restart: always
    depends_on:
      - coordinator
      - redis
      - cpu-node
    # GPU support - uncomment if you have NVIDIA GPU support configured with docker
    runtime: nvidia

  gpu1:
    environment:
      - CUDA_VISIBLE_DEVICES=1
    extends:
      service: gpu0

  gpu2:
    environment:
      - CUDA_VISIBLE_DEVICES=2
    extends:
      service: gpu0

  gpu3:
    environment:
      - CUDA_VISIBLE_DEVICES=3
    extends:
      service: gpu0

  gpu4:
    environment:
      - CUDA_VISIBLE_DEVICES=4
    extends:
      service: gpu0

  gpu5:
    environment:
      - CUDA_VISIBLE_DEVICES=5
    extends:
      service: gpu0

  gpu6:
    environment:
      - CUDA_VISIBLE_DEVICES=6
    extends:
      service: gpu0

  gpu7:
    environment:
      - CUDA_VISIBLE_DEVICES=7
    extends:
      service: gpu0

volumes:
  redis_data:
  postgresql_data:
```

We also need to update the `Dockerfile.node_gpu` to remove the fallback to SSH. The final `Dockerfile.node_gpu` should look like this:

```bash
#
# Build Stage
#
FROM --platform=linux/amd64 nvidia/cuda:13.0.1-devel-ubuntu22.04 AS build

# Install dependencies
RUN apt-get update -y && \
  apt-get install -y --no-install-recommends \
  # For Rust builds, OpenSSL, pkg-config
  openssl \
  libssl-dev \
  pkg-config \
  # General build tools for native dependencies
  build-essential \
  libclang-dev \
  diffutils \
  gcc \
  m4 \
  make \
  # CUDA NVTX library
  libnvtoolsext1 \
  # Utilities
  wget \
  tar \
  unzip \
  git \
  curl \
  openssh-client \
  && apt-get clean && \
  rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl https://sh.rustup.rs -sSf | bash -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"
COPY rust-toolchain.toml rust-toolchain.toml
RUN rustup show
ENV RUST_BACKTRACE=full

# Install golang
ENV GO_VERSION=1.22.1
RUN wget -q https://golang.org/dl/go$GO_VERSION.linux-amd64.tar.gz && \
  tar -C /usr/local -xzf go$GO_VERSION.linux-amd64.tar.gz && \
  rm go$GO_VERSION.linux-amd64.tar.gz
ENV PATH=$PATH:/usr/local/go/bin

# Install sp1 toolchain
ENV CARGO_NET_GIT_FETCH_WITH_CLI=true
RUN curl -L https://sp1.succinct.xyz | bash && ~/.sp1/bin/sp1up --version 6.0.0

# Install protoc
ENV PROTOC_ZIP=protoc-29.4-linux-x86_64.zip
RUN curl -OL https://github.com/protocolbuffers/protobuf/releases/download/v29.4/$PROTOC_ZIP && \
  unzip -o $PROTOC_ZIP -d /usr/local bin/protoc && \
  unzip -o $PROTOC_ZIP -d /usr/local 'include/*' && \
  rm -f $PROTOC_ZIP

# Install CMake
RUN CMAKE_VERSION=3.31.4 && \
    wget -q https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/cmake-${CMAKE_VERSION}-linux-x86_64.sh && \
    chmod +x cmake-${CMAKE_VERSION}-linux-x86_64.sh && \
    ./cmake-${CMAKE_VERSION}-linux-x86_64.sh --skip-license --prefix=/usr/local && \
    rm cmake-${CMAKE_VERSION}-linux-x86_64.sh && \
    cmake --version

# Setup SSH known hosts (actual auth configured during build)
RUN mkdir -p -m 0700 ~/.ssh && ssh-keyscan github.com >> ~/.ssh/known_hosts || true

# Application source code
WORKDIR /app
COPY . .

# Environment variables for the build
ARG BUILD_PROFILE=release
ENV BUILD_PROFILE=$BUILD_PROFILE

ARG RUSTFLAGS=""
ENV RUSTFLAGS="$RUSTFLAGS"

ARG FEATURES="gpu"
ENV FEATURES=$FEATURES

ARG VERGEN_GIT_SHA
ENV VERGEN_GIT_SHA=$VERGEN_GIT_SHA

# Build the application
# Uses BuildKit secrets mount to securely pass private token without exposing it in image layers
RUN --mount=type=ssh \
  --mount=type=secret,id=private_pull_token,required=false \
  --mount=type=cache,target=/root/.cargo/git \
  --mount=type=cache,target=/root/.cargo/registry \
  --mount=type=cache,target=/app/target \
  set -e; \
  echo "Building with profile: $BUILD_PROFILE | features: $FEATURES | rustflags: $RUSTFLAGS"; \
  if [ -f /run/secrets/private_pull_token ]; then \
    PRIVATE_TOKEN=$(cat /run/secrets/private_pull_token); \
    GIT_URL_BASE="https://${PRIVATE_TOKEN}@github.com/"; \
    git config --global --replace-all url."${GIT_URL_BASE}".insteadOf "https://github.com/"; \
    echo "Using HTTPS + token for git (private cargo deps enabled)" >&2; \
  fi; \
  echo "Building with profile: $BUILD_PROFILE | features: $FEATURES | rustflags: $RUSTFLAGS"; \
  cargo build --profile=$BUILD_PROFILE --features=$FEATURES --bin sp1-cluster-node; \
  cp target/$BUILD_PROFILE/sp1-cluster-node /sp1-cluster-node; \
  # Clean up any git credentials that might have been cached
  git config --global --unset-all url."${GIT_URL_BASE}".insteadOf || true; \
  unset PRIVATE_TOKEN GIT_URL_BASE || true

# Runtime stage
FROM --platform=linux/amd64 nvidia/cuda:13.0.1-runtime-ubuntu22.04 AS runtime

RUN \
  apt-get update -y && \
  apt-get install -y --no-install-recommends \
  ca-certificates \
  wget && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create a non-root user and group for better security
RUN groupadd --gid 1001 appgroup && \
  useradd --uid 1001 --gid appgroup --shell /bin/false --create-home appuser

# Copy the built application binaries from the build stage
COPY --from=build /sp1-cluster-node /app/sp1-cluster-node

# Set ownership to the non-root user and ensure the binary is executable
RUN chown appuser:appgroup /app/sp1-cluster-node && \
  chmod +x /app/sp1-cluster-node

# Set the user to the non-root user
USER appuser

CMD ["/app/sp1-cluster-node"]
```

### Step 4: Build docker images
You **must** build the docker images that use the locally modified sp1-cluster code with updated timeouts using the following commands before starting the cluster:

```bash
docker build -t sp1-cluster-local:base -f infra/Dockerfile .
docker build -t sp1-cluster-local:node-gpu -f infra/Dockerfile.node_gpu .
```

### Step 5: Install NVIDIA Container Toolkit (If Necessary)
If you get an error `Error response from daemon: unknown or invalid runtime name: nvidia` when building or starting docker compose, your VM doesn't have the NVIDIA runtime installed for Docker.

Run these commands to install it (assuming Ubuntu):
```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg && \
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Step 6: Start the Private Cluster using Docker Compose
Run the following command inside the `sp1-cluster/` directory (adjusting the `gpuX` services to match how many GPUs your VM has) to spin up the private cluster for proof generation:

```bash
docker compose -f infra/docker-compose.yml up -d postgresql redis api coordinator cpu-node gpu0 gpu1 gpu2 gpu3 gpu4 gpu5 gpu6 gpu7
```

### Verifying Modified Binaries
To ensure that your cluster is truly using the locally built, patched binaries with the increased timeouts, you can observe the docker logs and verify the artifact's Time-To-Live (TTL) in Redis while a proof is generating.

**1. Using Redis CLI to check TTL**
When the patched node worker uploads artifacts, it will set their expiration to your newly configured 240 hours (864,000 seconds) instead of the default 4 hours. You can verify this directly in the Redis container:

```bash
# 1. Find the name of your Redis container
docker ps | grep redis

# 2. Open an interactive redis-cli session (replace the container name as needed)
docker exec -it <redis_container_name> redis-cli

# 3. Inside the Redis CLI, fetch the keys and check a TTL
127.0.0.1:6379> keys *
1) "artifact:your-proof-id-or-hash"
127.0.0.1:6379> ttl "artifact:your-proof-id-or-hash"
(integer) 863985
```
If the command outputs a number close to `864000` (240 hours), your modified binary is successfully handling the job. If it is close to `14400` (4 hours), the old, unpatched binary is still running.

**2. Checking Node Logs**
You can also inspect the logs of one of your GPU worker nodes to check for successful task registration and artifact uploads using the new parameters:
```bash
docker logs -f <gpu_container_name> # e.g., sp1-cluster-gpu0-1
```


### Generating Proofs on the Cluster

To generate proofs using the cluster, invoke the `run_proofs.sh` script with the `--proving-mode "multi-gpu"` flag. For complex circuits, it is recommended to run the script in the background and monitor the output logs.

Refer to the [README.md](../README.md) for detailed definitions of standard parameters (such as `--num-tests`, `--qubit-counts`, etc.).

```bash
# Execute proof generation in the background
./run_proofs.sh --num-tests 64 --kmx "testdata/your_circuit.kmx" --qubit-counts 1450 --toffoli-counts 2200000 --total-ops 20000000 --proving-mode "multi-gpu" > proofs/your_circuit/log_run.out 2>&1 &

# Monitor progress
tail -f proofs/your_circuit/log_run.out
```

Once complete, the output proofs and verification keys will be saved in the `proofs/` directory relative to the circuit name.
