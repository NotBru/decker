<?php
use MediaWiki\Extension\Scribunto\Engines\LuaCommon\LibraryBase;

class WikibaseStubLibrary extends LibraryBase {
    public function register() {
        return $this->getEngine()->registerInterface(
            __DIR__ . '/wikibaseStub.lua', [], []
        );
    }
}
