/**
 * Ax-Easy Lyricist: pure formatting / parsing helpers (no DOM).
 * Shared by the admin screen and the Node unit tests.
 *
 * @package AxEasy_Lyricist
 */
( function ( root, factory ) {
	'use strict';
	var api = factory();
	if ( typeof module === 'object' && module.exports ) {
		module.exports = api;
	} else {
		root.AxeasyLyricistFormats = api;
	}
}( typeof self !== 'undefined' ? self : this, function () {
	'use strict';

	var DEFAULT_LAST_CUE = 4; // Seconds, when the audio duration is unknown.

	function pad( n, len ) {
		var s = String( n );
		while ( s.length < len ) {
			s = '0' + s;
		}
		return s;
	}

	function isNum( t ) {
		return typeof t === 'number' && isFinite( t );
	}

	/** Seconds -> "mm:ss.xx" (minutes may exceed 99). */
	function fmtLrcTime( t ) {
		var cs = Math.round( Math.max( 0, t ) * 100 );
		var mm = Math.floor( cs / 6000 );
		var ss = Math.floor( ( cs % 6000 ) / 100 );
		return pad( mm, 2 ) + ':' + pad( ss, 2 ) + '.' + pad( cs % 100, 2 );
	}

	/** Seconds -> "HH:MM:SS<sep>mmm". */
	function fmtClock( t, sep ) {
		var ms = Math.round( Math.max( 0, t ) * 1000 );
		var hh = Math.floor( ms / 3600000 );
		var mm = Math.floor( ( ms % 3600000 ) / 60000 );
		var ss = Math.floor( ( ms % 60000 ) / 1000 );
		return pad( hh, 2 ) + ':' + pad( mm, 2 ) + ':' + pad( ss, 2 ) + sep + pad( ms % 1000, 3 );
	}

	function fmtSrtTime( t ) {
		return fmtClock( t, ',' );
	}

	function fmtVttTime( t ) {
		return fmtClock( t, '.' );
	}

	/**
	 * Parse a user-typed time: "ss", "ss.xx", "m:ss", "mm:ss.xx", "hh:mm:ss,mmm".
	 * Returns seconds or null.
	 */
	function parseTime( str ) {
		if ( str === null || str === undefined ) {
			return null;
		}
		var s = String( str ).trim().replace( ',', '.' );
		if ( s === '' ) {
			return null;
		}
		var m = /^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d*)?)$/.exec( s );
		if ( ! m ) {
			return null;
		}
		var h = 0, mi = 0, sec = parseFloat( m[ 3 ] );
		if ( m[ 1 ] !== undefined && m[ 2 ] !== undefined ) {
			h = parseInt( m[ 1 ], 10 );
			mi = parseInt( m[ 2 ], 10 );
		} else if ( m[ 1 ] !== undefined ) {
			mi = parseInt( m[ 1 ], 10 );
		}
		var total = h * 3600 + mi * 60 + sec;
		return isFinite( total ) ? Math.round( total * 1000 ) / 1000 : null;
	}

	/**
	 * Stamped lines -> cues sorted by start, each ending where the next starts.
	 * The last cue ends at the audio duration (or start + 4 s when unknown).
	 */
	function buildCues( lines, duration ) {
		var stamped = [];
		( lines || [] ).forEach( function ( l, i ) {
			if ( l && isNum( l.time ) && String( l.text || '' ).trim() !== '' ) {
				stamped.push( { start: l.time, text: String( l.text ).trim(), i: i } );
			}
		} );
		stamped.sort( function ( a, b ) {
			return a.start - b.start || a.i - b.i;
		} );
		return stamped.map( function ( c, k ) {
			var end;
			if ( k + 1 < stamped.length ) {
				end = stamped[ k + 1 ].start;
			} else if ( isNum( duration ) && duration > c.start ) {
				end = duration;
			} else {
				end = c.start + DEFAULT_LAST_CUE;
			}
			return { start: c.start, end: Math.max( end, c.start ), text: c.text };
		} );
	}

	function cleanMeta( v ) {
		return String( v || '' ).replace( /[\r\n\]]+/g, ' ' ).trim();
	}

	function buildLrc( lines, meta ) {
		meta = meta || {};
		var out = [];
		[ 'ti', 'ar', 'al' ].forEach( function ( k ) {
			var v = cleanMeta( meta[ k ] );
			if ( v ) {
				out.push( '[' + k + ':' + v + ']' );
			}
		} );
		buildCues( lines, null ).forEach( function ( c ) {
			out.push( '[' + fmtLrcTime( c.start ) + ']' + c.text );
		} );
		return out.length ? out.join( '\n' ) + '\n' : '';
	}

	function buildSrt( lines, duration ) {
		return buildCues( lines, duration ).map( function ( c, k ) {
			return ( k + 1 ) + '\n' + fmtSrtTime( c.start ) + ' --> ' + fmtSrtTime( c.end ) + '\n' + c.text + '\n';
		} ).join( '\n' );
	}

	function escapeVtt( s ) {
		return s.replace( /&/g, '&amp;' ).replace( /</g, '&lt;' ).replace( />/g, '&gt;' );
	}

	function buildVtt( lines, duration ) {
		var cues = buildCues( lines, duration ).map( function ( c ) {
			return fmtVttTime( c.start ) + ' --> ' + fmtVttTime( c.end ) + '\n' + escapeVtt( c.text ) + '\n';
		} );
		return 'WEBVTT\n\n' + cues.join( '\n' );
	}

	/* ---- Language helpers ---- */

	var BCP47 = {
		ell: 'el', gre: 'el', eng: 'en', deu: 'de', ger: 'de', fra: 'fr', fre: 'fr', spa: 'es', ita: 'it',
		ara: 'ar', heb: 'he', rus: 'ru', por: 'pt', nld: 'nl', dut: 'nl', tur: 'tr', jpn: 'ja', zho: 'zh',
		chi: 'zh', kor: 'ko', pol: 'pl', swe: 'sv', nor: 'no', dan: 'da', fin: 'fi', bul: 'bg', ron: 'ro',
		rum: 'ro', ukr: 'uk', srp: 'sr', hrv: 'hr', alb: 'sq', sqi: 'sq', hin: 'hi', fas: 'fa', per: 'fa'
	};

	/** "ell" when the lyrics look Greek (>= 30% of letters), else "eng". Mirrors the PHP side. */
	function detectLang( lines ) {
		var text = ( lines || [] ).map( function ( l ) {
			return l && l.text ? l.text : '';
		} ).join( ' ' );
		var letters = 0;
		var greek = 0;
		for ( var i = 0; i < text.length; i++ ) {
			var c = text.charCodeAt( i );
			if ( ( c >= 0x0370 && c <= 0x03FF ) || ( c >= 0x1F00 && c <= 0x1FFF ) ) {
				greek++;
				letters++;
			} else if ( /[A-Za-z\u00C0-\u024F\u0400-\u04FF\u0590-\u05FF\u0600-\u06FF\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]/.test( text.charAt( i ) ) ) {
				letters++;
			}
		}
		return letters && greek / letters >= 0.3 ? 'ell' : 'eng';
	}

	/** ISO 639-2 (or '' = auto) -> BCP 47 tag for xml:lang. */
	function bcp47( code, lines ) {
		var c = String( code || '' ).toLowerCase();
		if ( c.length !== 3 ) {
			c = detectLang( lines );
		}
		return BCP47[ c ] || c;
	}

	/* ---- TTML (Apple Music style, TTML 1.0) ---- */

	function xmlEscape( s ) {
		return String( s )
			// Characters that are not allowed in XML 1.0 at all.
			.replace( /[\u0000-\u0008\u000B\u000C\u000E-\u001F\uFFFE\uFFFF]/g, '' )
			.replace( /&/g, '&amp;' )
			.replace( /</g, '&lt;' )
			.replace( />/g, '&gt;' )
			.replace( /"/g, '&quot;' )
			.replace( /'/g, '&apos;' );
	}

	/** Seconds -> TTML clock-time "HH:MM:SS.mmm". */
	function fmtTtmlTime( t ) {
		return fmtClock( t, '.' );
	}

	function buildTtml( lines, meta, duration ) {
		meta = meta || {};
		var cues = buildCues( lines, duration );
		var lang = bcp47( meta.lang, lines );
		var title = String( meta.ti || '' ).trim();
		var artist = String( meta.ar || '' ).trim();
		var out = [];
		out.push( '<?xml version="1.0" encoding="UTF-8"?>' );
		out.push( '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata" xmlns:itunes="http://music.apple.com/lyric-ttml-internal" itunes:timing="Line" xml:lang="' + xmlEscape( lang ) + '">' );
		if ( title || artist ) {
			out.push( '  <head>' );
			out.push( '    <metadata>' );
			if ( title ) {
				out.push( '      <ttm:title>' + xmlEscape( title ) + '</ttm:title>' );
			}
			if ( artist ) {
				out.push( '      <ttm:agent type="person" xml:id="v1">' );
				out.push( '        <ttm:name type="full">' + xmlEscape( artist ) + '</ttm:name>' );
				out.push( '      </ttm:agent>' );
			}
			out.push( '    </metadata>' );
			out.push( '  </head>' );
		}
		if ( ! cues.length ) {
			out.push( '  <body/>' );
		} else {
			var end = cues[ cues.length - 1 ].end;
			out.push( '  <body dur="' + fmtTtmlTime( end ) + '">' );
			// The div starts at 0 so the <p> times are absolute both for Apple's
			// reader and for strict TTML (where child times are relative to the
			// parent's begin).
			out.push( '    <div begin="' + fmtTtmlTime( 0 ) + '" end="' + fmtTtmlTime( end ) + '">' );
			cues.forEach( function ( c ) {
				out.push( '      <p begin="' + fmtTtmlTime( c.start ) + '" end="' + fmtTtmlTime( c.end ) + '"' + ( artist ? ' ttm:agent="v1"' : '' ) + '>' + xmlEscape( c.text ) + '</p>' );
			} );
			out.push( '    </div>' );
			out.push( '  </body>' );
		}
		out.push( '</tt>' );
		return out.join( '\n' ) + '\n';
	}

	/** TTML time expression -> seconds (clock-time, offset-time, Apple "M:SS.mmm"). */
	function parseTtmlTime( v ) {
		var s = String( v || '' ).trim();
		var m = /^(\d+(?:\.\d+)?)(h|m|s|ms)$/.exec( s );
		if ( m ) {
			var n = parseFloat( m[ 1 ] );
			var mult = { h: 3600, m: 60, s: 1, ms: 0.001 }[ m[ 2 ] ];
			return Math.round( n * mult * 1000 ) / 1000;
		}
		m = /^(\d+):(\d{2}):(\d{2}):(\d+)$/.exec( s ); // hh:mm:ss:frames (assume 30 fps).
		if ( m ) {
			return Math.round( ( parseInt( m[ 1 ], 10 ) * 3600 + parseInt( m[ 2 ], 10 ) * 60 + parseInt( m[ 3 ], 10 ) + parseInt( m[ 4 ], 10 ) / 30 ) * 1000 ) / 1000;
		}
		return parseTime( s );
	}

	function xmlUnescape( s ) {
		return String( s ).replace( /&(#x[0-9a-fA-F]+|#\d+|amp|lt|gt|quot|apos);/g, function ( all, e ) {
			if ( e.charAt( 0 ) === '#' ) {
				var cp = e.charAt( 1 ) === 'x' ? parseInt( e.slice( 2 ), 16 ) : parseInt( e.slice( 1 ), 10 );
				try {
					return String.fromCodePoint( cp );
				} catch ( err ) {
					return '';
				}
			}
			return { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" }[ e ];
		} );
	}

	function attr( tag, name ) {
		var m = new RegExp( '\\s' + name + '\\s*=\\s*(?:"([^"]*)"|\'([^\']*)\')' ).exec( tag );
		return m ? ( m[ 1 ] !== undefined ? m[ 1 ] : m[ 2 ] ) : null;
	}

	/** Parse TTML (Apple Music lyrics or plain TTML/DFXP) into lines. */
	function parseTtml( text ) {
		var src = String( text || '' ).replace( /^\uFEFF/, '' ).replace( /<!--[\s\S]*?-->/g, '' );
		var meta = { ti: '', ar: '', al: '' };
		var t = /<(?:\w+:)?title\b[^>]*>([\s\S]*?)<\/(?:\w+:)?title>/.exec( src );
		if ( t ) {
			meta.ti = xmlUnescape( t[ 1 ].replace( /<[^>]*>/g, '' ) ).trim();
		}
		var a = /<(?:\w+:)?name\b[^>]*>([\s\S]*?)<\/(?:\w+:)?name>/.exec( src );
		if ( a ) {
			meta.ar = xmlUnescape( a[ 1 ].replace( /<[^>]*>/g, '' ) ).trim();
		}
		var lines = [];
		var re = /<(?:\w+:)?p\b([^>]*)>([\s\S]*?)<\/(?:\w+:)?p>/g;
		var m;
		while ( ( m = re.exec( src ) ) ) {
			var begin = attr( m[ 1 ], 'begin' );
			var body = xmlUnescape( m[ 2 ].replace( /<(?:\w+:)?br\s*\/?>/g, ' ' ).replace( /<[^>]*>/g, '' ) ).replace( /\s+/g, ' ' ).trim();
			if ( body ) {
				lines.push( { text: body, time: begin !== null ? parseTtmlTime( begin ) : null } );
			}
		}
		lines.sort( function ( x, y ) {
			if ( x.time === null || y.time === null ) {
				return ( x.time === null ) - ( y.time === null );
			}
			return x.time - y.time;
		} );
		return { lines: lines, meta: meta };
	}

	function build( format, lines, meta, duration ) {
		if ( format === 'srt' ) {
			return buildSrt( lines, duration );
		}
		if ( format === 'vtt' ) {
			return buildVtt( lines, duration );
		}
		if ( format === 'ttml' ) {
			return buildTtml( lines, meta, duration );
		}
		return buildLrc( lines, meta );
	}

	/** Parse LRC (incl. multiple time tags per line, [offset:], word tags). */
	function parseLrc( text ) {
		var meta = { ti: '', ar: '', al: '' };
		var offset = 0;
		var stamped = [];
		var plain = [];
		var order = 0;
		String( text || '' ).replace( /^\uFEFF/, '' ).split( /\r\n|\r|\n/ ).forEach( function ( raw ) {
			var line = raw.trim();
			if ( ! line ) {
				return;
			}
			var times = [];
			var rest = line;
			var m;
			var tagRe = /^\[([^\]]*)\]/;
			while ( ( m = tagRe.exec( rest ) ) ) {
				var tag = m[ 1 ];
				var tm = /^(\d+):(\d{1,2})(?:[.:](\d{1,3}))?$/.exec( tag.trim() );
				if ( tm ) {
					var frac = tm[ 3 ] ? parseInt( tm[ 3 ], 10 ) / Math.pow( 10, tm[ 3 ].length ) : 0;
					times.push( parseInt( tm[ 1 ], 10 ) * 60 + parseInt( tm[ 2 ], 10 ) + frac );
				} else {
					var mm = /^([a-zA-Z]+):(.*)$/.exec( tag );
					if ( mm ) {
						var key = mm[ 1 ].toLowerCase();
						if ( key === 'ti' || key === 'ar' || key === 'al' ) {
							meta[ key ] = mm[ 2 ].trim();
						} else if ( key === 'offset' ) {
							offset = parseInt( mm[ 2 ], 10 ) || 0;
						}
					} else {
						break; // Not a tag; treat the rest as text.
					}
				}
				rest = rest.slice( m[ 0 ].length );
			}
			var body = rest.replace( /<\d+:\d{1,2}(?:[.:]\d{1,3})?>/g, '' ).trim();
			if ( ! body ) {
				return;
			}
			if ( times.length ) {
				times.forEach( function ( t ) {
					stamped.push( { text: body, time: t, o: order++ } );
				} );
			} else if ( rest === line ) {
				plain.push( { text: body, time: null } );
			}
		} );
		stamped.forEach( function ( l ) {
			l.time = Math.max( 0, Math.round( ( l.time - offset / 1000 ) * 1000 ) / 1000 );
		} );
		stamped.sort( function ( a, b ) {
			return a.time - b.time || a.o - b.o;
		} );
		var lines = stamped.map( function ( l ) {
			return { text: l.text, time: l.time };
		} ).concat( plain );
		return { lines: lines, meta: meta };
	}

	/** Parse SRT or WebVTT into lines (cue start times; multi-line cues joined). */
	function parseSubtitles( text ) {
		var lines = [];
		var blocks = String( text || '' ).replace( /^\uFEFF/, '' ).replace( /\r\n|\r/g, '\n' ).split( /\n\s*\n/ );
		blocks.forEach( function ( block ) {
			var rows = block.split( '\n' );
			for ( var i = 0; i < rows.length; i++ ) {
				var m = /^\s*((?:\d+:)?\d+:\d+[.,]\d+)\s*-->/.exec( rows[ i ] );
				if ( m ) {
					var body = rows.slice( i + 1 ).join( ' ' ).replace( /<[^>]*>/g, '' )
						.replace( /&lt;/g, '<' ).replace( /&gt;/g, '>' ).replace( /&amp;/g, '&' )
						.replace( /\s+/g, ' ' ).trim();
					if ( body ) {
						lines.push( { text: body, time: parseTime( m[ 1 ] ) } );
					}
					return;
				}
			}
		} );
		lines.sort( function ( a, b ) {
			return a.time - b.time;
		} );
		return { lines: lines, meta: { ti: '', ar: '', al: '' } };
	}

	function parseAny( text, filename ) {
		var name = String( filename || '' ).toLowerCase();
		if ( /\.(ttml|dfxp|xml)$/.test( name ) || /<tt[\s>]/.test( text ) ) {
			return parseTtml( text );
		}
		if ( /\.(srt|vtt)$/.test( name ) || /^\uFEFF?WEBVTT/.test( text ) || /-->/.test( text ) ) {
			return parseSubtitles( text );
		}
		return parseLrc( text );
	}

	/** Make a filename safe on Windows/macOS while keeping spaces and Unicode. */
	function sanitizeFilename( name ) {
		var s = String( name || '' )
			.replace( /[\u0000-\u001f\u007f]/g, '' )
			.replace( /[<>:"/\\|?*]/g, ' ' )
			.replace( /\s+/g, ' ' )
			.trim()
			.replace( /[. ]+$/, '' )
			.replace( /^[. ]+/, '' );
		if ( /^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$/i.test( s ) ) {
			s = '_' + s;
		}
		if ( s.length > 150 ) {
			s = s.slice( 0, 150 ).trim();
		}
		return s || 'lyrics';
	}

	/**
	 * Base filename (no extension): "Artist - Title".
	 * Title priority: attachment/ID3 title, then [ti:], then audio filename.
	 */
	function buildBaseName( info ) {
		info = info || {};
		var fileBase = String( info.filename || '' ).replace( /\.[^.]+$/, '' );
		var title = String( info.title || '' ).trim() || String( info.ti || '' ).trim() || fileBase;
		var artist = String( info.artist || '' ).trim();
		var base = title;
		if ( artist && title.toLowerCase().indexOf( artist.toLowerCase() + ' - ' ) !== 0 ) {
			base = artist + ' - ' + title;
		}
		return sanitizeFilename( base );
	}

	/* ---- Tiny ZIP (STORE, UTF-8 names) for "Download all" ---- */

	var CRC_TABLE = null;
	function crc32( bytes ) {
		if ( ! CRC_TABLE ) {
			CRC_TABLE = [];
			for ( var n = 0; n < 256; n++ ) {
				var c = n;
				for ( var k = 0; k < 8; k++ ) {
					c = ( c & 1 ) ? ( 0xEDB88320 ^ ( c >>> 1 ) ) : ( c >>> 1 );
				}
				CRC_TABLE[ n ] = c >>> 0;
			}
		}
		var crc = 0xFFFFFFFF;
		for ( var i = 0; i < bytes.length; i++ ) {
			crc = CRC_TABLE[ ( crc ^ bytes[ i ] ) & 0xFF ] ^ ( crc >>> 8 );
		}
		return ( crc ^ 0xFFFFFFFF ) >>> 0;
	}

	function utf8( str ) {
		if ( typeof TextEncoder !== 'undefined' ) {
			return new TextEncoder().encode( str );
		}
		var bin = unescape( encodeURIComponent( str ) );
		var out = new Uint8Array( bin.length );
		for ( var i = 0; i < bin.length; i++ ) {
			out[ i ] = bin.charCodeAt( i );
		}
		return out;
	}

	/** Text -> UTF-8 bytes, optionally with a BOM (EF BB BF). */
	function encodeFile( text, bom ) {
		return utf8( ( bom ? '\uFEFF' : '' ) + String( text ).replace( /^\uFEFF/, '' ) );
	}

	/**
	 * Bytes of an imported file -> text. Honours a UTF-8 / UTF-16 BOM (and
	 * strips it); valid UTF-8 without BOM is used as is; anything else is
	 * read as Greek Windows-1253 (the usual legacy encoding for Greek LRCs).
	 */
	function decodeText( bytes ) {
		var enc = 'utf-8';
		var start = 0;
		if ( bytes.length >= 3 && bytes[ 0 ] === 0xEF && bytes[ 1 ] === 0xBB && bytes[ 2 ] === 0xBF ) {
			start = 3;
		} else if ( bytes.length >= 2 && bytes[ 0 ] === 0xFF && bytes[ 1 ] === 0xFE ) {
			enc = 'utf-16le';
			start = 2;
		} else if ( bytes.length >= 2 && bytes[ 0 ] === 0xFE && bytes[ 1 ] === 0xFF ) {
			enc = 'utf-16be';
			start = 2;
		}
		var body = bytes.subarray( start );
		var text;
		try {
			text = new TextDecoder( enc, { fatal: true, ignoreBOM: true } ).decode( body );
		} catch ( e ) {
			enc = 'windows-1253';
			try {
				text = new TextDecoder( enc ).decode( body );
			} catch ( e2 ) {
				enc = 'utf-8';
				text = new TextDecoder( 'utf-8' ).decode( body );
			}
		}
		return { text: text.replace( /^\uFEFF/, '' ), encoding: enc, bom: start > 0 };
	}

	/**
	 * @param {Array<{name:string,data:Uint8Array}>} files
	 * @param {Date} [date]
	 * @return {Uint8Array}
	 */
	function buildZip( files, date ) {
		date = date || new Date();
		var dosTime = ( date.getHours() << 11 ) | ( date.getMinutes() << 5 ) | ( Math.floor( date.getSeconds() / 2 ) );
		var dosDate = ( ( Math.max( 1980, date.getFullYear() ) - 1980 ) << 9 ) | ( ( date.getMonth() + 1 ) << 5 ) | date.getDate();
		var chunks = [];
		var central = [];
		var offset = 0;

		function u16( v ) {
			return [ v & 0xFF, ( v >>> 8 ) & 0xFF ];
		}
		function u32( v ) {
			return [ v & 0xFF, ( v >>> 8 ) & 0xFF, ( v >>> 16 ) & 0xFF, ( v >>> 24 ) & 0xFF ];
		}

		files.forEach( function ( f ) {
			var name = utf8( f.name );
			var data = f.data;
			var crc = crc32( data );
			var common = [].concat( u16( 20 ), u16( 0x0800 ), u16( 0 ), u16( dosTime ), u16( dosDate ), u32( crc ), u32( data.length ), u32( data.length ), u16( name.length ), u16( 0 ) );
			var local = new Uint8Array( [].concat( u32( 0x04034b50 ), common ) );
			chunks.push( local, name, data );
			var cen = new Uint8Array( [].concat( u32( 0x02014b50 ), u16( 20 ), common, u16( 0 ), u16( 0 ), u16( 0 ), u32( 0 ), u32( offset ) ) );
			central.push( cen, name );
			offset += local.length + name.length + data.length;
		} );

		var cenSize = central.reduce( function ( s, c ) {
			return s + c.length;
		}, 0 );
		var end = new Uint8Array( [].concat( u32( 0x06054b50 ), u16( 0 ), u16( 0 ), u16( files.length ), u16( files.length ), u32( cenSize ), u32( offset ), u16( 0 ) ) );
		var all = chunks.concat( central, [ end ] );
		var total = all.reduce( function ( s, c ) {
			return s + c.length;
		}, 0 );
		var out = new Uint8Array( total );
		var p = 0;
		all.forEach( function ( c ) {
			out.set( c, p );
			p += c.length;
		} );
		return out;
	}

	return {
		fmtLrcTime: fmtLrcTime,
		fmtSrtTime: fmtSrtTime,
		fmtVttTime: fmtVttTime,
		parseTime: parseTime,
		buildCues: buildCues,
		buildLrc: buildLrc,
		buildSrt: buildSrt,
		buildVtt: buildVtt,
		build: build,
		buildTtml: buildTtml,
		parseTtml: parseTtml,
		fmtTtmlTime: fmtTtmlTime,
		detectLang: detectLang,
		bcp47: bcp47,
		xmlEscape: xmlEscape,
		parseLrc: parseLrc,
		parseSubtitles: parseSubtitles,
		parseAny: parseAny,
		sanitizeFilename: sanitizeFilename,
		buildBaseName: buildBaseName,
		crc32: crc32,
		utf8: utf8,
		encodeFile: encodeFile,
		decodeText: decodeText,
		buildZip: buildZip
	};
} ) );
