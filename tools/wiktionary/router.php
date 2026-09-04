<?php
// Router for PHP's built-in server. Two jobs: serve /wiki/<title> as an
// article, and accept upstream's /w/ prefix for entry points, so a caller can
// swap only the host and keep every URL identical to en.wiktionary.org.
$path = parse_url( $_SERVER["REQUEST_URI"], PHP_URL_PATH );
$rewritten = preg_replace( "#^/w/#", "/", $path );
$file = __DIR__ . $rewritten;

// An entry point (api.php, index.php, load.php...) is executed here rather
// than handed back to the server: returning false re-dispatches on the
// original URI, which under /w/ names no file on disk.
if ( substr( $rewritten, -4 ) === ".php" && is_file( $file ) ) {
    $_SERVER["SCRIPT_NAME"] = $path;
    $_SERVER["SCRIPT_FILENAME"] = $file;
    require $file;
    return true;
}

// Real static assets, only when the path was not rewritten.
if ( $path === $rewritten && $path !== "/" && is_file( $file ) ) {
    return false;
}

if ( preg_match( '#^/wiki/(.*)$#', $path, $m ) ) {
    $_GET["title"] = rawurldecode( $m[1] );
    $_REQUEST["title"] = $_GET["title"];
}
$_SERVER["SCRIPT_NAME"] = "/w/index.php";
require __DIR__ . "/index.php";
