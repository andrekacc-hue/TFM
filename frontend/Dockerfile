# Admin Portal: build con Vite y servido por nginx.
#   docker build -f frontend/Dockerfile --build-arg VITE_SUPABASE_URL=... .
# Contexto de build: ./frontend (las variables VITE_* se fijan en el build: son públicas).

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .

ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_API_GATEWAY_URL=http://localhost:8000
ARG VITE_APP_NAME="Soporte TI Produbanco"
ARG VITE_AZURE_ENABLED=false
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY \
    VITE_API_GATEWAY_URL=$VITE_API_GATEWAY_URL \
    VITE_APP_NAME=$VITE_APP_NAME \
    VITE_AZURE_ENABLED=$VITE_AZURE_ENABLED

# En el contenedor no hay .env: Vite toma las VITE_* de las variables de entorno del build
RUN npx tsc -b && npx vite build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
# 127.0.0.1 y no localhost: en Alpine localhost resuelve a ::1 y nginx escucha solo en IPv4
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/healthz || exit 1
