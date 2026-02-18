"""同步 composed arguments 到 generated_arguments.json"""
import json
from pathlib import Path
from datetime import datetime
from app.services.argument_composer import compose_project_arguments

def main():
    # 生成组合论据
    result = compose_project_arguments('yaruo_qu', 'Ms. Yaruo Qu')

    # 转换成前端格式
    arguments = []
    for standard, args in result.get('composed', {}).items():
        for idx, arg in enumerate(args):
            arg_id = f'{standard}_{idx}'
            snippet_ids = []
            for layer in ['claim', 'proof', 'significance', 'context']:
                for item in arg.get(layer, []):
                    if item.get('snippet_id'):
                        snippet_ids.append(item['snippet_id'])

            arguments.append({
                'id': arg_id,
                'title': arg.get('title', ''),
                'subject': arg.get('group_key', ''),
                'standard_key': standard,
                'snippet_ids': snippet_ids,
                'exhibits': arg.get('exhibits', []),
                'confidence': arg.get('completeness', {}).get('score', 0) / 100.0,
                'is_ai_generated': True,
                'created_at': datetime.now().isoformat(),
                'layers': arg.get('layers', {}),
                'conclusion': arg.get('conclusion', ''),
                'completeness': arg.get('completeness', {})
            })

    output = {
        'project_id': 'yaruo_qu',
        'main_subject': 'Ms. Yaruo Qu',
        'arguments': arguments,
        'generated_at': datetime.now().isoformat(),
        'stats': result.get('statistics', {})
    }

    # 保存到 generated_arguments.json
    output_path = Path('data/projects/yaruo_qu/arguments/generated_arguments.json')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f'Generated {len(arguments)} composed arguments:')
    for arg in arguments:
        score = arg.get('completeness', {}).get('score', 0)
        print(f'  [{arg["standard_key"]}] {arg["title"]} ({score}%)')

    print(f'\nStats: {json.dumps(result.get("statistics", {}), indent=2)}')

if __name__ == '__main__':
    main()
