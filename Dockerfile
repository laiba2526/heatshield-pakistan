# Hugging Face Spaces (Docker SDK) image for the HeatShield dashboard.
# The container serves on port 7860 and refreshes the data hourly in-process.
FROM python:3.11-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONPATH=/home/user/app/src \
    PYTHONIOENCODING=utf-8 \
    HEATSHIELD_REFRESH_MINUTES=60
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .

EXPOSE 7860
# Build the document index first (the official PDFs are fetched from their
# publishers and hash-checked, because they are not openly licensed), then serve.
CMD ["sh", "-c", "python -m heatshield.rag.ingest || echo 'RAG index not built - documents unavailable'; exec streamlit run app/streamlit_app.py --server.port 7860 --server.address 0.0.0.0 --server.headless true"]
