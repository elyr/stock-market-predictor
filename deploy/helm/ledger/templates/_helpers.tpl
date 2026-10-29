{{/* Chart name */}}
{{- define "ledger.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Full name: the release name, plus the chart name unless it already contains it */}}
{{- define "ledger.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else if contains (include "ledger.name" .) .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "ledger.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/* Labels on every object */}}
{{- define "ledger.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "ledger.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector for the web server pods. It includes the component, so pods of the
scheduled jobs (same image, same app) never receive web traffic.
*/}}
{{- define "ledger.serverSelectorLabels" -}}
app.kubernetes.io/name: {{ include "ledger.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: server
{{- end }}

{{- define "ledger.mlflowSelectorLabels" -}}
app.kubernetes.io/name: {{ include "ledger.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: mlflow
{{- end }}

{{/* Selector for a supporting component: (dict "context" . "component" "grafana") */}}
{{- define "ledger.componentSelectorLabels" -}}
app.kubernetes.io/name: {{ include "ledger.name" .context }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/* Address of the MLflow server inside the cluster */}}
{{- define "ledger.mlflowUrl" -}}
{{ printf "http://%s-mlflow:5000" (include "ledger.fullname" .) }}
{{- end }}

{{- define "ledger.image" -}}
{{ printf "%s:%s" .Values.image.repository (toString .Values.image.tag) }}
{{- end }}

{{/* Demo and live data live in separate databases on the same volume */}}
{{- define "ledger.databasePath" -}}
{{- if eq .Values.mode "demo" }}/app/data/demo.db{{ else }}/app/data/predictions.db{{ end }}
{{- end }}

{{/* In-cluster address of the server, used by the jobs */}}
{{- define "ledger.serverUrl" -}}
{{ printf "http://%s:%v" (include "ledger.fullname" .) .Values.service.port }}
{{- end }}

{{/* Settings the chart refuses, with an explanation */}}
{{- define "ledger.validate" -}}
{{- if not (has .Values.mode (list "demo" "live")) }}
{{- fail (printf "mode must be \"demo\" or \"live\", got %q" (toString .Values.mode)) }}
{{- end }}
{{- if not (has .Values.database.type (list "sqlite" "postgresql")) }}
{{- fail (printf "database.type must be \"sqlite\" or \"postgresql\", got %q" (toString .Values.database.type)) }}
{{- end }}
{{- if not (has .Values.queue.type (list "inline" "redis")) }}
{{- fail (printf "queue.type must be \"inline\" or \"redis\", got %q" (toString .Values.queue.type)) }}
{{- end }}
{{- if and (gt (int .Values.replicaCount) 1) (not (include "ledger.scalable" .)) }}
{{- fail "replicaCount above 1 needs database.type=postgresql, queue.type=redis and mlflow.enabled: with SQLite or jobs inside the server, only one copy can run at a time" }}
{{- end }}
{{- if and (eq .Values.queue.type "redis") (not .Values.mlflow.enabled) }}
{{- fail "queue.type=redis needs mlflow.enabled: workers and servers must share the model registry" }}
{{- end }}
{{- end }}

{{/* Backup and restore: what is backed up, and the volumes it lives on (templates/backup.yaml) */}}
{{- define "ledger.backupItems" -}}
{{- if include "ledger.postgres" . }}
- --database
- app=$(DATABASE_URL)
{{- else }}
- --sqlite
- app={{ include "ledger.databasePath" . }}
{{- end }}
{{- if .Values.mlflow.enabled }}
- --sqlite
- mlflow=/mlflow/mlflow.db
- --dir
- mlflow-artifacts=/mlflow/artifacts
{{- else }}
- --sqlite
- mlflow=/app/data/mlflow-{{ ternary "demo" "predictions" (eq .Values.mode "demo") }}.db
- --dir
- mlflow-artifacts=/app/data/mlartifacts-{{ ternary "demo" "predictions" (eq .Values.mode "demo") }}
{{- end }}
{{- if .Values.dailyPrediction.enabled }}
- --dir
- predictions=/predictions
{{- end }}
{{- end }}
{{- define "ledger.backupVolumes" -}}
volumeMounts:
  - name: data
    mountPath: /app/data
  - name: backups
    mountPath: /backups
  {{- if .Values.mlflow.enabled }}
  - name: mlflow
    mountPath: /mlflow
  {{- end }}
  {{- if .Values.dailyPrediction.enabled }}
  - name: predictions
    mountPath: /predictions
  {{- end }}
{{- end }}
{{- define "ledger.backupClaims" -}}
volumes:
  - name: data
    persistentVolumeClaim:
      claimName: {{ include "ledger.fullname" . }}-data
  - name: backups
    persistentVolumeClaim:
      claimName: {{ include "ledger.fullname" . }}-backups
  {{- if .Values.mlflow.enabled }}
  - name: mlflow
    persistentVolumeClaim:
      claimName: {{ include "ledger.fullname" . }}-mlflow
  {{- end }}
  {{- if .Values.dailyPrediction.enabled }}
  - name: predictions
    persistentVolumeClaim:
      claimName: {{ include "ledger.fullname" . }}-predictions
  {{- end }}
{{- end }}

{{/* Database, queue and scaling */}}
{{- define "ledger.postgres" -}}
{{- if eq .Values.database.type "postgresql" }}true{{ end }}
{{- end }}

{{- define "ledger.inClusterPostgres" -}}
{{- if and (include "ledger.postgres" .) (not .Values.database.postgresql.url) (not .Values.database.postgresql.existingSecret) }}true{{ end }}
{{- end }}

{{- define "ledger.redisQueue" -}}
{{- if eq .Values.queue.type "redis" }}true{{ end }}
{{- end }}

{{- define "ledger.inClusterRedis" -}}
{{- if and (include "ledger.redisQueue" .) (not .Values.queue.redis.url) }}true{{ end }}
{{- end }}

{{/* Several server copies can run: shared database, jobs in workers, shared model registry */}}
{{- define "ledger.scalable" -}}
{{- if and (include "ledger.postgres" .) (include "ledger.redisQueue" .) .Values.mlflow.enabled }}true{{ end }}
{{- end }}

{{/* Secret holding the database URL (key: database-url) */}}
{{- define "ledger.databaseSecret" -}}
{{- .Values.database.postgresql.existingSecret | default (printf "%s-database" (include "ledger.fullname" .)) }}
{{- end }}

{{- define "ledger.redisUrl" -}}
{{- .Values.queue.redis.url | default (printf "redis://%s-redis:6379/0" (include "ledger.fullname" .)) }}
{{- end }}

{{/* Environment shared by the server, the workers and the backup jobs */}}
{{- define "ledger.appEnv" -}}
- name: DEMO_MODE
  value: {{ ternary "true" "false" (eq .Values.mode "demo") | quote }}
- name: DATABASE_PATH
  value: {{ include "ledger.databasePath" . | quote }}
{{- if include "ledger.postgres" . }}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "ledger.databaseSecret" . }}
      key: database-url
{{- end }}
- name: JOB_QUEUE
  value: {{ .Values.queue.type | quote }}
{{- if include "ledger.redisQueue" . }}
- name: REDIS_URL
  value: {{ include "ledger.redisUrl" . | quote }}
{{- end }}
# The alert scans are run by CronJobs when they are enabled
- name: INTERNAL_SCHEDULER
  value: {{ ternary "false" "true" .Values.signals.enabled | quote }}
{{- if .Values.mlflow.enabled }}
- name: MLFLOW_TRACKING_URI
  value: {{ include "ledger.mlflowUrl" . | quote }}
{{- with .Values.mlflow.uiUrl }}
- name: MLFLOW_UI_URL
  value: {{ . | quote }}
{{- end }}
{{- end }}
- name: LOG_FORMAT
  value: {{ .Values.logFormat | quote }}
{{- if .Values.configFile }}
- name: CONFIG_PATH
  value: /etc/ledger/config.yaml
{{- end }}
{{- if .Values.secrets.alphaVantageApiKey }}
- name: ALPHA_VANTAGE_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "ledger.fullname" . }}
      key: alpha-vantage-api-key
{{- end }}
{{- end }}

{{/*
Init container: wait until the services the app needs answer (MLflow,
PostgreSQL, Redis), so it starts cleanly instead of restarting until they do.
*/}}
{{- define "ledger.waitForDependencies" -}}
{{- $targets := list }}
{{- if .Values.mlflow.enabled }}{{ $targets = append $targets (printf "http %s/health" (include "ledger.mlflowUrl" .)) }}{{ end }}
{{- if include "ledger.inClusterPostgres" . }}{{ $targets = append $targets (printf "tcp %s-postgresql:5432" (include "ledger.fullname" .)) }}{{ end }}
{{- if include "ledger.inClusterRedis" . }}{{ $targets = append $targets (printf "tcp %s-redis:6379" (include "ledger.fullname" .)) }}{{ end }}
{{- if $targets }}
- name: wait-for-dependencies
  image: {{ include "ledger.image" . | quote }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  securityContext:
    {{- toYaml .Values.securityContext | nindent 4 }}
  command:
    - python
    - -c
    - |
      import socket, sys, time, urllib.request
      targets = sys.argv[1:]
      for target in targets:
          kind, address = target.split(" ", 1)
          for attempt in range(120):
              try:
                  if kind == "http":
                      urllib.request.urlopen(address, timeout=3)
                  else:
                      host, port = address.rsplit(":", 1)
                      socket.create_connection((host, int(port)), timeout=3).close()
                  print(f"{address} is up", flush=True)
                  break
              except Exception as e:
                  if attempt % 10 == 0: print(f"Waiting for {address}: {e}", flush=True)
                  time.sleep(3)
          else:
              raise SystemExit(f"{address} did not answer within 6 minutes")
    {{- range $targets }}
    - {{ . | quote }}
    {{- end }}
  resources:
    requests: { cpu: 10m, memory: 32Mi }
    limits: { cpu: 200m, memory: 128Mi }
{{- end }}
{{- end }}
