/* ***** BEGIN LICENSE BLOCK *****
 * Version: MPL 1.1/GPL 2.0/LGPL 2.1
 *
 * The contents of this file are subject to the Mozilla Public License Version
 * 1.1 (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 * http://www.mozilla.org/MPL/
 *
 * Software distributed under the License is distributed on an 'AS IS' basis,
 * WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
 * for the specific language governing rights and limitations under the
 * License.
 *
 * The Original Code is Bespin.
 *
 * The Initial Developer of the Original Code is
 * Mozilla.
 * Portions created by the Initial Developer are Copyright (C) 2009
 * the Initial Developer. All Rights Reserved.
 *
 * Contributor(s):
 *   Bespin Team (bespin@mozilla.com)
 *
 * Alternatively, the contents of this file may be used under the terms of
 * either the GNU General Public License Version 2 or later (the "GPL"), or
 * the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
 * in which case the provisions of the GPL or the LGPL are applicable instead
 * of those above. If you wish to allow use of your version of this file only
 * under the terms of either the GPL or the LGPL, and not to allow others to
 * use your version of this file under the terms of the MPL, indicate your
 * decision by deleting the provisions above and replace them with the notice
 * and other provisions required by the GPL or the LGPL. If you do not delete
 * the provisions above, a recipient may use your version of this file under
 * the terms of any one of the MPL, the GPL or the LGPL.
 *
 * ***** END LICENSE BLOCK ***** */

"define metadata";
({
    "description": "CSS syntax highlighter",
    "dependencies": {
        "syntax_manager": "0.0"
    },
    "provides": [
        {
            "ep": "syntax",
            "name": "css",
            "pointer": "#CSSSyntax",
            "fileexts": [ "css", "less" ]
        }
    ]
});
"end";

var Promise = require('bespin:promise').Promise;
var StandardSyntax = require('syntax_manager:controllers/standardsyntax').
    StandardSyntax;

var states = {
    start: [
        {
            //tags
            regex:  /^([\w]+)(?![a-zA-Z0-9_:])([,|{]*?)(?!;)(?!(;|%))/,  
            tag:    'keyword'
        },
        {
            //id
            regex:  /^#([a-zA-Z]*)(?=.*{*?)/,
            tag:    'error'
        },
        {
            //classes
            regex:  /^\.([a-zA-Z]*)(?=.*{*?)/,
            tag:    'string'
        },
        {
            //style names
			      regex: 	/^([a-zA-Z-]*)(?:\:)/,
			      tag:	'directive'
        },
        {
            regex:  /^\/\/.*/,
            tag:    'comment'
        },
        {
            regex:  /^\/\*/,
            tag:    'comment',
            then:   'comment'
        },
        {
            regex:  /^./,
            tag:    'plain'
        }
    ],

    comment: [
        {
            regex:  /^[^*\/]+/,
            tag:    'comment'
        },
        {
            regex:  /^\*\//,
            tag:    'comment',
            then:   'start'
        },
        {
            regex:  /^[*\/]/,
            tag:    'comment'
        }
    ]
};

exports.CSSSyntax = new StandardSyntax(states);
