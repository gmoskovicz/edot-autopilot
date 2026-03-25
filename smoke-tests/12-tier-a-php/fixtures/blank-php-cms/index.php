<?php
/**
 * Content Management API — PHP (Slim Framework)
 *
 * No observability. Run `Observe this project.` to add OpenTelemetry.
 *
 * Routes:
 *   GET  /health                — liveness probe
 *   GET  /api/v1/articles       — list articles
 *   GET  /api/v1/articles/{id}  — get article (from cache or DB)
 *   POST /api/v1/articles       — create article
 */

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

require __DIR__ . '/vendor/autoload.php';

$app = AppFactory::create();
$app->addErrorMiddleware(true, true, true);

// ── In-memory cache + store (replace with Redis + MySQL in production) ─────────
$cache    = [];
$articles = [];

// ── Helper: simulate Redis cache lookup ───────────────────────────────────────
function cacheGet(array &$cache, string $key): ?array
{
    if (isset($cache[$key])) {
        usleep(random_int(500, 3000)); // cache hit: ~0.5–3 ms
        return $cache[$key];
    }
    return null;
}

function cacheSet(array &$cache, string $key, array $value): void
{
    $cache[$key] = $value;
}

// ── Helper: simulate MySQL fetch + markdown render ────────────────────────────
function dbFetch(string $articleId): ?array
{
    usleep(random_int(20000, 80000)); // DB: 20–80 ms
    // Pretend article exists if ID is numeric
    if (!is_numeric($articleId)) return null;
    return [
        'id'         => $articleId,
        'title'      => "Article $articleId",
        'body_html'  => "<p>Content for article $articleId</p>",
        'author'     => 'editor@cms.example',
        'created_at' => date('c'),
    ];
}

function renderMarkdown(string $md): string
{
    usleep(random_int(5000, 25000)); // render: 5–25 ms
    return "<p>$md</p>"; // stub
}

// ── Routes ─────────────────────────────────────────────────────────────────────
$app->get('/health', function (Request $request, Response $response): Response {
    $response->getBody()->write(json_encode(['status' => 'ok']));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->get('/api/v1/articles', function (Request $request, Response $response) use (&$articles): Response {
    $response->getBody()->write(json_encode(array_values($articles)));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->get('/api/v1/articles/{id}', function (Request $request, Response $response, array $args) use (&$cache, &$articles): Response {
    $id       = $args['id'];
    $cacheKey = "article:$id";

    // Try cache first
    $cached = cacheGet($cache, $cacheKey);
    if ($cached !== null) {
        $response->getBody()->write(json_encode(array_merge($cached, ['cache_hit' => true])));
        return $response->withHeader('Content-Type', 'application/json');
    }

    // Fetch from DB
    $article = dbFetch($id) ?? ($articles[$id] ?? null);
    if ($article === null) {
        $error = json_encode(['error' => 'not found']);
        $response->getBody()->write($error);
        return $response->withStatus(404)->withHeader('Content-Type', 'application/json');
    }

    cacheSet($cache, $cacheKey, $article);
    $response->getBody()->write(json_encode(array_merge($article, ['cache_hit' => false])));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/api/v1/articles', function (Request $request, Response $response) use (&$cache, &$articles): Response {
    $body = json_decode((string) $request->getBody(), true);

    if (empty($body['title']) || empty($body['body_md'])) {
        $response->getBody()->write(json_encode(['error' => 'title and body_md required']));
        return $response->withStatus(400)->withHeader('Content-Type', 'application/json');
    }

    $id = (string) (count($articles) + 1);
    $article = [
        'id'         => $id,
        'title'      => $body['title'],
        'body_html'  => renderMarkdown($body['body_md']),
        'author'     => $body['author'] ?? 'anonymous',
        'created_at' => date('c'),
    ];
    $articles[$id] = $article;
    cacheSet($cache, "article:$id", $article);

    $response->getBody()->write(json_encode($article));
    return $response->withStatus(201)->withHeader('Content-Type', 'application/json');
});

$app->run();
