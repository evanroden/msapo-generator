"""The retained one-click evidence is passive and never reads human input."""

from pathlib import Path
import subprocess


def test_photo_observer_records_native_target_and_geometry_without_changing_action():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["node", "-e", r"""
      const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
      const listeners=new Map(),status={isConnected:true,dataset:{saveState:'pending'},
        getBoundingClientRect:()=>({x:100,y:-800,width:900,height:21})};
      const button={isConnected:true,textContent:'Add these photos',
        closest:q=>q==='button'||q==='.st-key-epc_pair_monthly_activity'?button:null,
        getBoundingClientRect:()=>({x:380,y:449,width:160,height:40})};
      const document={addEventListener:(t,f,c)=>{assert.equal(c,true);listeners.set(t,f)},
        querySelector:q=>q==='.enfra-browser-save-status'?status:{scrollTop:3952}};
      const window={},context={document,window,WeakMap,performance:{now:()=>123}};
      vm.runInNewContext(fs.readFileSync('scripts/qa_photo_action_observations.js','utf8'),context);
      assert.equal(listeners.size,5);
      for(const type of ['pointerdown','mousedown','pointerup','mouseup','click'])
        listeners.get(type)({type,target:button,isTrusted:true,clientX:443,clientY:449});
      const records=window.__enfraPhotoActionObservations();
      assert.equal(records.length,5);
      assert.ok(records.every(e=>e.action===e.target&&e.connected&&e.button.y===449&&e.status.height===21));
      assert.equal(records[0].scroll,3952);
      assert.equal(button.textContent,'Add these photos');
      assert.equal('value' in records[0],false);
      // A geometry change and a lost native target remain observable; the
      // recorder neither retries the click nor adjusts scroll or focus.
      button.getBoundingClientRect=()=>({x:380,y:521,width:160,height:40});
      listeners.get('mouseup')({type:'mouseup',target:{closest:()=>null},isTrusted:true,clientX:443,clientY:449});
      const lost=window.__enfraPhotoActionObservations().at(-1);
      assert.equal(lost.target,null);assert.equal(lost.button.y,521);
      for(let i=0;i<100;i++)listeners.get('mouseup')({type:'mouseup',target:button,isTrusted:true});
      assert.equal(window.__enfraPhotoActionObservations().length,96);
    """], cwd=root, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
