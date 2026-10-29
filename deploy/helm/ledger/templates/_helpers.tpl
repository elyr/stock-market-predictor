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
{{- if ne (int .Values.replicaCount) 1 }}
{{- fail "replicaCount must be 1: the app keeps its data in SQLite and runs jobs inside the server, so only one copy can run at a time" }}
{{- end }}
{{- end }}

{{/* Backup and restore: what is backed up, and the volumes it lives on (templates/backup.yaml) */}}
{{- define "ledger.backupItems" -}}
- --sqlite
- app={{ include "ledger.databasePath" . }}
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
