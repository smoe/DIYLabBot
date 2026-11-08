"""Stable local and geometry place identifiers from the shared rack definition."""
def places(rack):
    if rack['slot_order']!='row_major':raise ValueError('Unsupported rack slot order')
    result=[]
    for row in range(rack['rows']):
        for column in range(rack['columns']):
            slot=row*rack['columns']+column+1;local_id='Slot%02d'%slot
            result.append({'id':rack['id']+'.'+local_id,'place_id':local_id,
                           'slot':slot,'row':row,'column':column})
    return result
