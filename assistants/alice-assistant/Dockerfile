FROM python:3.11-slim  

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod -R 755 aiml_files

EXPOSE 5005

CMD ["python", "api_wrapper.py"] 