## Pasos para ejecutar el backend por primera vez

# 1. Clonar el repositorio y acceder a la carpeta del backend
git clone <URL_DEL_REPO>
cd <CARPETA_DEL_PROYECTO>

# 2. Crea y activa un entorno virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Instalar dependecias
pip install -r requirements.txt

# 4. Configura variables de entorno .env (por ahora no hay)

# 5. Ejecutar el backend
uvicorn app.main:app --port 8001



## Pasos para ejecutar
# 1. Activar el entorno
C:\venv\Scripts\Activate.ps1

# 2. Entrar a la carpeta backend
cd backend-prod

# 3. Ejecutar backend
uvicorn app.main:app --port 8001


# Entrar al enviroment
C:\venvs\backend-prod-env\Scripts\Activate.ps1

# Entrar a la carpeta backend
cd backend-prod

# Ejecutar backend
uvicorn app.main:app --port 8001

# Para levantarlo sin logs:
uvicorn app.main:app --no-access-log --port 8001

# Para ejecutar el frontend, debes encontrarte en la carpeta frontend-prod y es necesario tener un .env en la razís del front con lo siguiente:
VITE_API_BASE_URL=http://127.0.0.1:8001

# ejecutar
npm run dev
