FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Los_Angeles \
    JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64 \
    PATH=/opt/samapr-venv/bin:/opt/defects4j/framework/bin:/opt/spotbugs/bin:/usr/lib/jvm/java-11-openjdk-amd64/bin:${PATH} \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates cpanminus curl git jq make maven \
       openjdk-11-jdk-headless patch perl python3 python3-pip python3-venv \
       subversion unzip wget \
    && rm -rf /var/lib/apt/lists/*

COPY artifacts/cache/defects4j-master.zip /tmp/artifacts/defects4j-master.zip
COPY artifacts/cache/defects4j-gradle-dists-v3.zip /tmp/artifacts/defects4j-gradle-dists-v3.zip
COPY artifacts/cache/defects4j-gradle-deps-v3.zip /tmp/artifacts/defects4j-gradle-deps-v3.zip
COPY artifacts/cache/spotbugs-4.10.3.zip /tmp/artifacts/spotbugs-4.10.3.zip
COPY requirements-analysis.lock /tmp/requirements-analysis.lock

RUN cd /tmp/artifacts \
    && echo 'ba1e6bc011d4290a84d4df625cfd3e366c8062722bf6a4648586bff185d13c56  defects4j-master.zip' | sha256sum -c - \
    && echo '2ac17f3a57e47bf05e0f2e01aecb0d1b9147033554eeb7998480eb1b7fa6d4fd  defects4j-gradle-dists-v3.zip' | sha256sum -c - \
    && echo 'd94100d316e56ef510c44050706a2bea7594d12cc4c7357d36b35e6bb1536545  defects4j-gradle-deps-v3.zip' | sha256sum -c - \
    && echo 'e814ee5bf9665412658c4d684e45eae3cf993148a71bc8bc93fb343e92288151  spotbugs-4.10.3.zip' | sha256sum -c -

RUN cd /opt \
    && unzip -q /tmp/artifacts/defects4j-master.zip \
    && mv defects4j-master defects4j \
    && mkdir -p defects4j/framework/lib/build_systems/gradle \
    && cp /tmp/artifacts/defects4j-gradle-dists-v3.zip defects4j/framework/lib/build_systems/gradle/ \
    && cp /tmp/artifacts/defects4j-gradle-deps-v3.zip defects4j/framework/lib/build_systems/gradle/ \
    && cd defects4j \
    && cpanm --notest --installdeps . \
    && ./init.sh \
    && chmod -R a+rX /opt/defects4j

RUN cd /opt \
    && unzip -q /tmp/artifacts/spotbugs-4.10.3.zip \
    && mv spotbugs-4.10.3 spotbugs \
    && chmod -R a+rX /opt/spotbugs

RUN python3 -m venv /opt/samapr-venv \
    && /opt/samapr-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/samapr-venv/bin/pip install --no-cache-dir -r /tmp/requirements-analysis.lock \
    && rm -rf /tmp/artifacts /tmp/requirements-analysis.lock

RUN git config --system --add safe.directory /workspace

WORKDIR /workspace
CMD ["bash"]
