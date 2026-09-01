@echo off
REM Sobe o Jarvis (interface Streamlit). Duplo clique neste arquivo.
REM Criado em 2026-08-29 pra recuperacao rapida durante a demo -- ver PENDENCIAS.md
REM (metodo de apresentacao). Deixa a janela do terminal ABERTA de proposito:
REM fechar essa janela derruba o servidor.

cd /d "%~dp0"

echo ================================================
echo  Iniciando o Jarvis...
echo  NAO FECHE ESTA JANELA enquanto estiver usando.
echo  Endereco: http://localhost:8501
echo ================================================
echo.

call venv\Scripts\activate.bat
python -m streamlit run interface.py

echo.
echo O Jarvis parou. Feche esta janela ou rode de novo.
pause
