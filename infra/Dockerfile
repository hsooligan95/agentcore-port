# UNTESTED AGAINST AWS — never built for or deployed to AgentCore.
# This is the container shape AgentCore Runtime requires (ARM64, port
# 8080, /invocations + /ping), included so the deployment step is a
# reviewable artifact. Local conformance is proven WITHOUT this image:
# the harness serves the identical contract from serve.py.
FROM --platform=linux/arm64 python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY serve.py .
# factory-floor-agent is expected alongside at runtime in this pattern's
# local layout; a real image build would vendor both repos explicitly.
EXPOSE 8080
CMD ["python", "serve.py", "--host", "0.0.0.0", "--port", "8080"]
