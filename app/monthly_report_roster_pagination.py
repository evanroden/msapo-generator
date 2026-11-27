"""Keep explicit imported contact pairs with their nearby vendor, not a whole roster."""
import re


def keep_contact_groups(table, columns):
    if (len(columns)!=3 or re.sub(r'\W+',' ',columns[0]).strip().casefold()!='discipline'
            or columns[2].strip().casefold()!='msa'):
        return
    rows=table.rows
    def label(index):
        return ' '.join(rows[index].cells[0].text.casefold().split()).rstrip(':')
    for index in range(1,len(rows)-1):
        if (label(index)!='contact name' or label(index+1)!='contact number'
                or not rows[index].cells[1].text.strip() or not rows[index+1].cells[1].text.strip()
                or rows[index].cells[2].text.strip() or rows[index+1].cells[2].text.strip()):
            continue
        linked=[index]
        if (index>1 and label(index-1) not in ('contact name','contact number')
                and rows[index-1].cells[0].text.strip() and rows[index-1].cells[1].text.strip()):
            linked.insert(0,index-1)
        for number in linked:
            for cell in rows[number].cells:
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.keep_with_next=True
