FROM python:3.11-slim

# FFmpeg del gestor de paquetes + dependencias nativas de skia-python (raster CPU, sin X11/GPU)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libfontconfig1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Usuario sin privilegios; los videos se escriben en /out (montar un volumen)
RUN useradd --create-home archengine && mkdir /out && chown archengine /out
USER archengine
WORKDIR /out
VOLUME /out

ENTRYPOINT ["archengine"]
CMD ["doctor"]
