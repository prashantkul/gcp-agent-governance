FROM node:18-alpine AS builder
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM node:18-alpine
WORKDIR /app
COPY runtime/package*.json ./
RUN npm ci --omit=dev
COPY runtime/src/ ./src/
COPY --from=builder /app/build ./public/
EXPOSE 8080
ENV PORT=8080
CMD ["node", "src/index.js"]
