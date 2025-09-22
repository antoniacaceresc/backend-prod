# Para correr el código se debe activar el entorno virtual con los sig comandos:

python -m venv env
env\Scripts\activate

# Luego se debe entrar al backend y correr el main

cd backend\

uvicorn main:app --port 8001


# En caso de requerir dependencias, estas se encuentran en requirements.txt, que debe estar actualizado

# Para correr node localmente, se debe ir a la carpeta de node y correr
set PATH=%CD%\;%CD%\npm;%PATH%

# Luego en la carpeta de front se debe correr
npm run dev