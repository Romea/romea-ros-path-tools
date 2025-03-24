ARG FROM_IMAGE=ghcr.io/tirrex-roboterrium/tirrex_workspace
FROM ${FROM_IMAGE}
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl build-essential ca-certificates cmake \
        doxygen g++ git libeigen3-dev libgdal-dev libpython3-dev python3 python3-pip \
        python3-matplotlib python3-tk lcov libgtest-dev libtbb-dev swig libgeos-dev \
        gnuplot libtinyxml2-dev nlohmann-json3-dev libfftw3-dev

RUN git clone 'https://github.com/Fields2Cover/Fields2Cover.git' /tmp/f2c && \
    mkdir /tmp/f2c/build && \
    cd /tmp/f2c/build && \
    cmake -DBUILD_PYTHON=ON -DBUILD_TEST=OFF -DBUILD_TUTORIALS=OFF -DBUILD_TESTING=OFF \
        -DCMAKE_INSTALL_PREFIX=/opt/f2c .. && \
    make -j && \
    make install
