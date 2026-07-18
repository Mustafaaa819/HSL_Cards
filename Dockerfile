FROM node:22-slim AS frontend-build
WORKDIR /frontend
# Deliberately NOT copying package-lock.json: it's regenerated on the
# developer's Windows machine, and a persistent npm bug
# (github.com/npm/cli/issues/4828 — hit twice already in this project, once
# for local Vite/rolldown, once here for lightningcss) can silently skip
# installing a platform-specific optional native binary, and an existing
# lockfile from a different OS makes that worse by steering resolution.
# Upgrading npm and resolving fresh from package.json alone, with no
# lockfile influence at all, is the standard workaround for this bug.
COPY frontend/package.json ./
RUN npm install -g npm@latest && npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend-build /frontend/dist ./static

# HF Spaces (Docker SDK) always routes traffic to port 7860. Render sets
# $PORT itself; default to 7860 so the same image works unmodified on both.
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
