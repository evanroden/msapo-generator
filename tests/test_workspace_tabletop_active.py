"""Execute the actual tabletop selector against hosted failure geometry."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_tabletop_preview_uses_the_same_active_section_as_navigation():
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const geometry = require('./app/workspace_geometry.js');
const source = fs.readFileSync('app/workspace_layout.js', 'utf8');
const start = source.indexOf('    function updateActive(context) {');
const end = source.indexOf('    let waitingForGesture', start);
assert.ok(start >= 0 && end > start);
assert.ok(source.includes('navigation?.update(context,sample);\n        updateActive(context);'),
    'the coordinator must resolve the current reading line before preview visibility');
function run({activityTop, organizationBottom, navigationActive, previous = null, navigation = {}, mode = 'tabletop'}) {
    const pairs = [
        {id:'monthly_organization', pair:{dataset:{}, box:{y:-38.8125,height:organizationBottom + 38.8125}}},
        {id:'monthly_activity', pair:{dataset:{}, box:{y:activityTop,height:1243.34375}}},
        {id:'monthly_scorecards', pair:{dataset:{}, box:{y:1740.6875,height:798.53125}}},
    ];
    const state = {active:previous, navigationActive};
    const context = {mode, editor:{y:416}};
    vm.runInNewContext(source.slice(start, end) + '\nupdateActive(context);', {
        geometry, state, pairs, navigation, context, rect:pair=>pair.box,
    });
    return {state,pairs,active:pairs.filter(({pair})=>pair.dataset.epcActive === 'true').map(({id})=>id)};
}
// Exact failure rectangles from both hosted engines: the old y+32 line
// lies within Organization even though Back/Next has landed on Activity.
for (const [activityTop,organizationBottom] of [[481.34375,465.34375],[481.375,465.375]]) {
    let result = run({activityTop,organizationBottom,navigationActive:'monthly_activity'});
    assert.equal(result.state.active,'monthly_activity');
    assert.deepEqual(result.active,['monthly_activity'],'only the current editor preview is exposed');
    result = run({activityTop,organizationBottom,navigationActive:'monthly_activity',previous:'monthly_organization'});
    assert.deepEqual(result.active,['monthly_activity'],'a stale prior tabletop preview cannot override navigation');
    result = run({activityTop,organizationBottom,navigationActive:'monthly_scorecards',previous:'monthly_activity'});
    assert.deepEqual(result.active,['monthly_scorecards'],'forward navigation uses the same coordinator');
    result = run({activityTop,organizationBottom,navigationActive:'monthly_activity',previous:'monthly_scorecards'});
    assert.deepEqual(result.active,['monthly_activity'],'reverse navigation uses the same coordinator');
    result = run({activityTop,organizationBottom,navigationActive:'monthly_activity',navigation:null});
    assert.deepEqual(result.active,['monthly_organization'],'other tools retain their existing geometric reading line');
    result = run({activityTop,organizationBottom,navigationActive:null});
    assert.deepEqual(result.active,['monthly_organization'],'uninitialized navigation retains geometric fallback');
    result = run({activityTop,organizationBottom,navigationActive:'not_a_present_section'});
    assert.deepEqual(result.active,['monthly_organization'],'missing navigation target does not blank every preview');
    result = run({activityTop,organizationBottom,navigationActive:'monthly_activity',mode:'wide'});
    assert.deepEqual(result.active,[],'ordinary wide previews remain unconfined');
}
'''
    subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True, text=True)
