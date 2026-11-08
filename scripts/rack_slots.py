"""Stable row-major place identifiers from the shared rack definition."""
def places(rack):
    if rack['slot_order']!='row_major':raise ValueError('Unsupported rack slot order')
    return [{'id':rack['id']+'.Slot%02d'%(row*rack['columns']+col+1),
             'slot':row*rack['columns']+col+1,'row':row,'column':col}
            for row in range(rack['rows']) for col in range(rack['columns'])]
