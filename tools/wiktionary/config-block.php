<?php
# The settings a MediaWiki needs to render Wiktionary. Append this file's body
# to the LocalSettings.php that maintenance/install.php generates, BEFORE
# importing a single page: $wgCapitalLinks and $wgCompressRevisions decide what
# the import writes and are worthless set afterwards.
#
#   cp -r tools/wiktionary/extensions/WikibaseStub ~/mw/extensions/
#   echo 'require_once "/path/to/decker/tools/wiktionary/config-block.php";' \
#       >> ~/mw/LocalSettings.php
#
# Paths below are built from $IP, MediaWiki's own install path, so this file
# works wherever it is required from.
#
# Why each of these is here, and what breaks without it, is in
# docs/execution/local-wiktionary.md. Nothing below is a secret: the database
# credentials, $wgSecretKey and $wgUpgradeKey stay in LocalSettings.php and out
# of this repository.

# ---------------- decker local Wiktionary ----------------
# Case-sensitive titles, as Wiktionary has. MUST be set before importing:
# otherwise "Template:foo" is stored as "Template:Foo" and nothing resolves.
$wgCapitalLinks = false;

# Gzip each revision's text. Wikitext compresses ~4x. Only affects rows
# written while it is on, so it has to be set before the import too.
$wgCompressRevisions = true;

wfLoadExtension( 'Scribunto' );
$wgScribuntoDefaultEngine = 'luastandalone';
$wgScribuntoEngineConf['luastandalone']['luaPath'] = '/usr/bin/lua5.1';
# Wiktionary's data modules do not fit Scribunto's default memory cap.
$wgScribuntoEngineConf['luastandalone']['memoryLimit'] = 2 * 1024 * 1024 * 1024;
$wgScribuntoEngineConf['luastandalone']['cpuLimit'] = 120;

wfLoadExtension( 'ParserFunctions' );
$wgPFEnableStringFunctions = true;
wfLoadExtension( 'TemplateStyles' );
wfLoadExtension( 'Cite' );

# Emit <div class="mw-heading"> wrappers, as Wikimedia's parser does.
$wgParserEnableLegacyHeadingDOM = false;

# Work under whatever host and port it is reached by.
$wgServer = WebRequest::detectServer();
$wgArticlePath = "/wiki/$1";
$wgUsePathInfo = true;

$wgShowExceptionDetails = true;
$wgMaxShellMemory = 4 * 1024 * 1024;
$wgMaxShellTime = 300;
$wgLanguageCode = "en";

# Modules call mw.title.new(x, 'Wiktionary'); the project namespace is derived
# from the sitename, so "Wiktionary (local)" made that namespace unrecognised.
$wgSitename = "Wiktionary";
$wgMetaNamespace = "Wiktionary";
# Wiktionary entries make far more expensive parser calls than the default 100.
$wgExpensiveParserFunctionLimit = 2000;

# A stub mw.wikibase: this mirror has no Wikidata repository, and installing a
# real Wikibase Client would mean either importing Wikidata's dumps or calling
# wikidata.org over the network -- the exact query exposure this mirror avoids.
# Modules that ask for Wikidata now get nothing back instead of an error.
# Autoload, never require_once: at LocalSettings time Scribunto's own
# autoloader does not exist yet, so `extends LibraryBase` fatals.
$wgAutoloadClasses['WikibaseStubLibrary'] = "$IP/extensions/WikibaseStub/WikibaseStubLibrary.php";
$wgHooks['ScribuntoExternalLibraries'][] = static function ( $engine, array &$extraLibraries ) {
    if ( $engine === 'lua' ) {
        $extraLibraries['mw.wikibase'] = WikibaseStubLibrary::class;
    }
    return true;
};
# Match upstream's layout: entry points under /w/, articles under /wiki/.
$wgScriptPath = "/w";
