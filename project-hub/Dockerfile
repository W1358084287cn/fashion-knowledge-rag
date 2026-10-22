FROM node:22-alpine

WORKDIR /app

COPY server.js ./
COPY web ./web

ENV PORT=3003 \
    DATA_DIR=/data

EXPOSE 3003

CMD ["node", "server.js"]
