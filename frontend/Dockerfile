#################################
# Etapa 1: Build con Node.js    #
#################################
FROM node:18-alpine AS build
WORKDIR /app

# 1) Copiamos solo package.json y package-lock.json para cachear dependencias
COPY package.json package-lock.json ./
RUN npm ci

# 2) Copiamos todo el código de tu proyecto (incluido vite.config.js, src/, public/, etc.)
COPY . .

# 3) Generamos el build de producción; Vite crea /app/dist
RUN npm run build

########################################
# Etapa 2: Servir los estáticos con NGINX #
########################################
FROM nginx:stable-alpine AS production

# 1) Limpiamos cualquier contenido previo que Nginx trae por defecto
RUN rm -rf /usr/share/nginx/html/*

# 2) Ahora copiamos la carpeta /app/dist (donde está el build de Vite) a la carpeta de Nginx
COPY --from=build /app/dist /usr/share/nginx/html

# 3) Exponemos el puerto 80 (Nginx escuchará ahí)
EXPOSE 80

# 4) Arrancamos Nginx en primer plano
CMD ["nginx", "-g", "daemon off;"]