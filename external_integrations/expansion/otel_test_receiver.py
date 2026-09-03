import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

LOG = r"C:\Users\gabri\Desktop\Jarvis2.0\external_integrations\expansion\otel_test_capture.jsonl"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        request = ExportTraceServiceRequest()
        request.ParseFromString(body)

        records = []

        for resource_spans in request.resource_spans:
            service_name = None

            for attr in resource_spans.resource.attributes:
                if attr.key == "service.name":
                    service_name = attr.value.string_value

            for scope_spans in resource_spans.scope_spans:
                for span in scope_spans.spans:
                    records.append({
                        "service": service_name,
                        "span": span.name,
                        "trace_id": span.trace_id.hex(),
                        "span_id": span.span_id.hex(),
                    })

        with open(LOG, "a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        for record in records:
            print("TRACE:", record, flush=True)

        response = ExportTraceServiceResponse().SerializeToString()

        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        pass


print("OTLP TEST RECEIVER ATTIVO SU http://127.0.0.1:4318")
HTTPServer(("127.0.0.1", 4318), Handler).serve_forever()
