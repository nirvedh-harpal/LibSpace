from django.core.management.base import BaseCommand
from reservations.models import Seat

class Command(BaseCommand):
    help = 'Populate seats with structured numbering pattern'

    def add_arguments(self, parser):
        parser.add_argument('--blocks', type=str, nargs='+', default=['A', 'B', 'C'],
                          help='List of block letters (default: A B C)')
        parser.add_argument('--floors', type=int, default=3,
                          help='Number of floors per block (default: 3)')
        parser.add_argument('--seats-per-floor', type=int, default=10,
                          help='Number of seats per floor (default: 10)')
        parser.add_argument('--clear', action='store_true',
                          help='Clear existing seats before creating new ones')

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing seats...')
            Seat.objects.all().delete()

        blocks = options['blocks']
        floors = options['floors']
        seats_per_floor = options['seats_per_floor']

        seats_created = 0
        for block in blocks:
            for floor in range(1, floors + 1):
                for seat in range(1, seats_per_floor + 1):
                    seat_number = f"{block}.{floor:02d}.{seat:02d}"
                    description = f"Block {block}, Floor {floor}, Seat {seat}"
                    location = f"Block {block}, Floor {floor}"
                    
                    Seat.objects.get_or_create(
                        number=seat_number,
                        defaults={
                            'description': description,
                            'location': location,
                            'is_active': True
                        }
                    )
                    seats_created += 1
                    self.stdout.write(f'Created seat: {seat_number} - {description}')

        self.stdout.write(self.style.SUCCESS(f'Successfully created {seats_created} seats'))