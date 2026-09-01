@echo off
REM Duplo clique aqui para impedir que o PC durma durante a apresentacao.
REM Fechar esta janela desfaz -- nada fica alterado no Windows.
REM Ver manter_pc_acordado.ps1 para o porque de nao mexer no plano de energia.

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manter_pc_acordado.ps1"
