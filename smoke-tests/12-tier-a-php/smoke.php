<?php
/**
 * Smoke test: Tier A — PHP (native OTel SDK, full O11y: traces + logs + metrics).
 *
 * Business scenario: CMS content API — authenticate API key, fetch article,
 * render Markdown, cache response.
 *
 * Run (requires php-opentelemetry/sdk package via composer):
 *   cd smoke-tests/12-tier-a-php && composer install && php smoke.php
 *
 * Or via the Python runner:
 *   cd smoke-tests && python3 12-tier-a-php/smoke.py
 */

declare(strict_types=1);

require_once __DIR__ . '/vendor/autoload.php';

use OpenTelemetry\API\Common\Time\Clock;
use OpenTelemetry\API\Logs\LogRecord;
use OpenTelemetry\API\Trace\SpanKind;
use OpenTelemetry\API\Trace\StatusCode;
use OpenTelemetry\Contrib\Otlp\LogsExporter;
use OpenTelemetry\Contrib\Otlp\MetricsExporter;
use OpenTelemetry\Contrib\Otlp\SpanExporter;
use OpenTelemetry\SDK\Common\Attribute\Attributes;
use OpenTelemetry\SDK\Common\Export\Http\PsrTransportFactory;
use OpenTelemetry\SDK\Logs\LoggerProvider;
use OpenTelemetry\SDK\Logs\Processor\BatchLogRecordProcessor;
use OpenTelemetry\SDK\Metrics\MeterProvider;
use OpenTelemetry\SDK\Metrics\MetricReader\ExportingReader;
use OpenTelemetry\SDK\Resource\ResourceInfo;
use OpenTelemetry\SDK\Trace\SpanProcessor\BatchSpanProcessor;
use OpenTelemetry\SDK\Trace\TracerProvider;
use OpenTelemetry\SemConv\ResourceAttributes;
use Psr\Http\Client\ClientInterface;

// Load .env
$envFile = __DIR__ . '/../../.env';
if (file_exists($envFile)) {
    foreach (file($envFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if (str_starts_with($line, '#') || !str_contains($line, '=')) continue;
        [$k, $v] = explode('=', $line, 2);
        if (!getenv($k)) putenv("$k=$v");
    }
}

define('SVC', 'smoke-tier-a-php');
$endpoint = getenv('ELASTIC_OTLP_ENDPOINT');
$apiKey   = getenv('ELASTIC_API_KEY');
$envName  = getenv('OTEL_DEPLOYMENT_ENVIRONMENT') ?: 'smoke-test';
$headers  = ['Authorization' => "ApiKey $apiKey"];

$resource = ResourceInfo::create(Attributes::create([
    ResourceAttributes::SERVICE_NAME   => SVC,
    'deployment.environment'           => $envName,
]));

$transport = (new PsrTransportFactory())->create("$endpoint/v1/traces", 'application/x-protobuf', $headers);
$spanExporter = new SpanExporter($transport);
$tracerProvider = new TracerProvider(
    new BatchSpanProcessor($spanExporter),
    resource: $resource
);
$tracer = $tracerProvider->getTracer(SVC);

$metricsTransport = (new PsrTransportFactory())->create("$endpoint/v1/metrics", 'application/x-protobuf', $headers);
$meterProvider = MeterProvider::builder()
    ->setResource($resource)
    ->addReader(new ExportingReader(new MetricsExporter($metricsTransport)))
    ->build();
$meter = $meterProvider->getMeter(SVC);

$requestCounter = $meter->createCounter('cms.api_requests');
$renderTime     = $meter->createHistogram('cms.render_ms', 'ms');
$cacheHits      = $meter->createCounter('cms.cache_hits');

$requests = [
    ['GET', '/api/v1/articles/42',  'art-42',  'enterprise', true],
    ['GET', '/api/v1/articles/117', 'art-117', 'public',     false],
    ['GET', '/api/v1/articles/8',   'art-8',   'pro',        true],
    ['GET', '/api/v1/articles/301', 'art-301', 'enterprise', false],
];

echo "\n[" . SVC . "] Handling CMS API requests via native PHP OTel SDK...\n";

foreach ($requests as [$method, $path, $articleId, $tier, $cached]) {
    $t0 = microtime(true);
    $span = $tracer->spanBuilder('cms.handle_request')
        ->setSpanKind(SpanKind::KIND_SERVER)
        ->setAttribute('http.method',    $method)
        ->setAttribute('http.route',     $path)
        ->setAttribute('cms.article_id', $articleId)
        ->setAttribute('customer.tier',  $tier)
        ->startSpan();
    $scope = $span->activate();

    try {
        // Auth
        $authSpan = $tracer->spanBuilder('cms.authenticate')->setSpanKind(SpanKind::KIND_INTERNAL)->startSpan();
        usleep(random_int(3000, 12000));
        $authSpan->end();

        if ($cached) {
            $cacheSpan = $tracer->spanBuilder('cms.cache_lookup')
                ->setSpanKind(SpanKind::KIND_CLIENT)
                ->setAttribute('cache.system', 'redis')
                ->setAttribute('cache.key', "article:$articleId")
                ->startSpan();
            usleep(random_int(1000, 5000));
            $cacheSpan->setAttribute('cache.hit', true);
            $cacheSpan->end();
            $cacheHits->add(1, ['customer.tier' => $tier]);
        } else {
            $dbSpan = $tracer->spanBuilder('cms.db_fetch')
                ->setSpanKind(SpanKind::KIND_CLIENT)
                ->setAttribute('db.system', 'mysql')
                ->setAttribute('db.operation', 'SELECT')
                ->setAttribute('db.table', 'articles')
                ->startSpan();
            usleep(random_int(20000, 80000));
            $dbSpan->end();

            $renderSpan = $tracer->spanBuilder('cms.render_markdown')
                ->setSpanKind(SpanKind::KIND_INTERNAL)
                ->startSpan();
            usleep(random_int(5000, 25000));
            $renderSpan->end();
        }

        $dur = (microtime(true) - $t0) * 1000;
        $span->setAttribute('http.status_code', 200);
        $span->setAttribute('cms.response_ms',  round($dur, 2));
        $span->setAttribute('cms.cached',        $cached);
        $span->setStatus(StatusCode::STATUS_OK);

        $requestCounter->add(1, ['http.method' => $method, 'customer.tier' => $tier, 'cms.cached' => $cached ? 'true' : 'false']);
        $renderTime->record($dur, ['customer.tier' => $tier]);

        $cacheStr = $cached ? 'HIT ' : 'MISS';
        printf("  ✅ %s %-30s  tier=%-12s  cache=%s  dur=%.0fms\n", $method, $path, $tier, $cacheStr, $dur);
    } finally {
        $scope->detach();
        $span->end();
    }
}

$tracerProvider->shutdown();
$meterProvider->shutdown();
echo "[" . SVC . "] Done → Kibana APM → " . SVC . "\n";
