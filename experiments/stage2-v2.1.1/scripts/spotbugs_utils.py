from __future__ import annotations
import xml.etree.ElementTree as ET
from pathlib import Path
from common import defects4j_export, run_cmd

def run_spotbugs(cfg, workdir: Path, report: Path, log: Path, label: str):
    d4j=cfg['defects4j_bin']; timeout=int(cfg['timeouts']['spotbugs'])
    bin_classes=defects4j_export(d4j, workdir, 'dir.bin.classes', log.with_name(log.stem+'_export_bin.log'), timeout)
    if not bin_classes or not (workdir/bin_classes).exists(): return False, 'No production class directory'
    cp=defects4j_export(d4j, workdir, 'cp.compile', log.with_name(log.stem+'_export_cp.log'), timeout)
    cmd=[cfg['spotbugs_bin'],'-textui','-effort:max','-low','-xml:withMessages','-output',str(report)]
    if cp: cmd += ['-auxclasspath',cp]
    cmd += [str(workdir/bin_classes)]
    code,out=run_cmd(cmd, workdir, log, timeout)
    return report.exists() and report.stat().st_size>0, out

def parse_alerts(report: Path):
    rows=[]
    if not report.exists() or report.stat().st_size==0: return rows
    root=ET.parse(report).getroot()
    for bi in root.findall('.//BugInstance'):
        method_el=bi.find('Method'); source_el=bi.find('SourceLine')
        if source_el is None and method_el is not None: source_el=method_el.find('SourceLine')
        rows.append({
            'pattern':bi.attrib.get('type',''),
            'category':bi.attrib.get('category',''),
            'file':((source_el.attrib.get('sourcepath','') or source_el.attrib.get('sourcefile','')) if source_el is not None else '').replace('\\','/'),
            'method':method_el.attrib.get('name','') if method_el is not None else '',
            'start_line':source_el.attrib.get('start','') if source_el is not None else '',
            'end_line':source_el.attrib.get('end','') if source_el is not None else '',
        })
    return rows

def count_target(alerts, patterns, target_file, target_method):
    patterns=set(patterns); target_file=target_file.replace('\\','/')
    matched=[]
    for a in alerts:
        file_ok=(a['file']==target_file or target_file.endswith(a['file']) or a['file'].endswith(target_file))
        method_ok=(not target_method or a['method']==target_method)
        if a['pattern'] in patterns and file_ok and method_ok: matched.append(a)
    return len(matched), matched

def warning_delta(before_alerts, after_alerts, static_evidence):
    """Compare the exact Contract targets using buggy/patched reports from one attempt."""
    entries=[]
    for evidence in static_evidence:
        loc=evidence['location']; pattern=evidence['pattern']
        before_count,before=count_target(before_alerts,[pattern],loc['file'],loc.get('method',''))
        after_count,after=count_target(after_alerts,[pattern],loc['file'],loc.get('method',''))
        entries.append({
            'pattern':pattern,'file':loc['file'],'method':loc.get('method',''),
            'before_count':before_count,'after_count':after_count,
            'removed':before_count>0 and after_count==0,
            'new_same_count':max(0,after_count-before_count),
            'before_matches':before,'after_matches':after,
        })
    return {
        'targets':entries,
        'all_targets_present_before':bool(entries) and all(x['before_count']>0 for x in entries),
        'target_warning_removed':bool(entries) and all(x['removed'] for x in entries),
        'new_same_warning_count':sum(x['new_same_count'] for x in entries),
    }
