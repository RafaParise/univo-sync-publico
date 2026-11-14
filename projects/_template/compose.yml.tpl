services:
  __NAME__:
    image: __IMAGE__
    container_name: __NAME__
    # Para código próprio, troque "image" por:  build: ./projects/__NAME__/src
    volumes:
      - ./data/__NAME__:/data
    networks: [parise]
    restart: unless-stopped
