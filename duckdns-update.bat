@echo off
set SUBDOMAIN=ppappspt
set TOKEN=SEU_TOKEN_DUCKDNS
powershell Invoke-WebRequest -Uri "https://www.duckdns.org/update?domains=%SUBDOMAIN%&token=%TOKEN%&ip=" -UseBasicParsing
